// Combined RAK4631 storage dispatch, using the real application applier.
// Reuse the existing SD fixture's flash/media helpers without changing its
// Tower/QSPI regression entry point. Both external media are present so a
// mistaken fallback can succeed and be detected instead of merely failing.
#include <stdint.h>
static uint8_t QSPI_FLASH[2u * 1024u * 1024u];
#define main sd_fixture_main
#include "sd_apply_test.c"
#undef main

void ota_qspi_set_rak_source(uint8_t marker) {
  g_qspi_source_marker = marker;
  g_qspi_slot_c = marker == GPREGRET2_OTA_STAGE_RAK15001;
}
bool ota_qspi_init(void) { g_qspi_init_calls++; return true; }
void ota_qspi_deinit(void) { g_qspi_deinit_calls++; }
uint32_t ota_qspi_capacity(void) { return sizeof(QSPI_FLASH); }
bool ota_qspi_read(uint32_t offset, void *out, uint32_t len) {
  g_qspi_read_calls++;
  if ((uint64_t)offset + len > sizeof(QSPI_FLASH)) return false;
  memcpy(out, QSPI_FLASH + offset, len);
  return true;
}
bool ota_qspi_write(uint32_t offset, const void *data, uint32_t len) {
  g_qspi_write_calls++;
  if ((uint64_t)offset + len > sizeof(QSPI_FLASH)) return false;
  const uint8_t *source = data;
  for (uint32_t i = 0; i < len; i++) QSPI_FLASH[offset + i] &= source[i];
  return true;
}

static void prepare(const uint8_t *base, uint32_t size) {
  reset_device(base, size);
  memset(QSPI_FLASH, 0xFF, sizeof(QSPI_FLASH));
  g_gpregret2 = GPREGRET2_OTA_STAGE_SD;
  memset(&g_hybrid, 0, sizeof(g_hybrid));
}

static void auth_crc(void) {
  SD_AUTH.crc32 = mota_sd_auth_crc32((const uint8_t *)&SD_AUTH,
                                    offsetof(mota_sd_auth_t, crc32));
  SD_AUTH.crc32_inv = ~SD_AUTH.crc32;
}

static void stage_nor(const uint8_t *mota, uint32_t size) {
  if (size > sizeof(QSPI_FLASH)) abort();
  memcpy(QSPI_FLASH, mota, size);
  memcpy(QSPI_FLASH + MOTA_SD_AUTH_APPROVAL_OFFSET, APRV, sizeof(APRV));
}

static void stage_internal(const uint8_t *mota, uint32_t size) {
  uint32_t start = (MOTA_NRF52_STAGE_CEILING_LEGACY - size) & ~(PAGE - 1u);
  memcpy(FLASH + start, mota, size);
  memcpy(FLASH + start + MOTA_SD_AUTH_APPROVAL_OFFSET, APRV, sizeof(APRV));
}

static int no_app_write(const uint8_t *base, uint32_t size) {
  return g_bank0 == BANK_VALID_APP_V && g_settings_writes == 0 &&
         g_app_write_while_valid == 0 &&
         memcmp(FLASH + MOTA_NRF52_APP_BASE, base, size) == 0;
}

static int no_nor(void) {
  return g_qspi_init_calls == 0 && g_qspi_deinit_calls == 0 &&
         g_qspi_read_calls == 0 && g_qspi_write_calls == 0 &&
         g_qspi_source_marker == -1;
}

static int committed(const uint8_t *image, uint32_t size) {
  return g_bank0 == BANK_VALID_APP_V && g_crc == 0x1234 && g_size == size &&
         g_settings_writes == 2 && g_app_write_while_valid == 0 &&
         g_gpregret == 0 && g_gpregret2 == 0xB8u &&
         memcmp(FLASH + MOTA_NRF52_APP_BASE, image, size) == 0;
}

#ifdef MOTA_ROLLBACK_HOST_TEST
static bool trial_watchdog_available;
static unsigned trial_watchdog_starts;

bool otah_start_trial_watchdog(void) {
  trial_watchdog_starts++;
  return trial_watchdog_available;
}

static void cold_boot(void) {
  g_gpregret = 0;
  g_sd_source = g_sd_active = g_sd_auth_loaded = g_qspi_source = false;
  g_cache_page = g_cache_dirty = 0;
  rollback_armed_page = 0;
}

static bool run_rollback(const uint8_t *base, uint32_t base_len,
                         uint8_t *next, uint32_t next_len,
                         const uint8_t *delta, uint32_t delta_len,
                         uint32_t medium, uint32_t page, int scenario) {
  prepare(base, base_len);
  const bool interrupted = scenario == 2 || scenario == 6;
  uint32_t package_len = delta_len;
  uint8_t *full = NULL;
  if (scenario != 6) {
    memcpy(next + 64, MOTA_ROLLBACK_APP_CAPABILITY, 8);
    full = make_full_mota(next, next_len, &package_len);
  }
  const uint8_t *package = full ? full : delta;
  g_gpregret2 = medium;
  const bool sd = medium == GPREGRET2_OTA_STAGE_SD;
  if (sd) {
    if (!stage_external_mota(package, package_len)) abort();
  } else {
    stage_nor(package, package_len);
  }
  free(full);

  mota_rollback_record_t record = {
    .magic = MOTA_ROLLBACK_MAGIC, .media = medium,
    .offset = sd ? 128u : 0x100000u,
    .previous_size = base_len, .next_size = next_len, .phase = MOTA_ROLLBACK_READY,
  };
  uint8_t *backup = sd ? SD_CARD + record.offset * MOTA_SD_SECTOR_SIZE : QSPI_FLASH + record.offset;
  memcpy(backup, base, base_len);
  sha256_bytes(base, base_len, record.previous_hash);
  sha256_bytes(next, next_len, record.next_hash);
  record.crc32 = mota_rollback_crc(&record);
  memcpy(FLASH + page, &record, sizeof(record));
  const mota_rollback_record_t *saved = rollback_record_at(page);
  trial_watchdog_available = scenario != 5;
  trial_watchdog_starts = 0;

  if (scenario == 3) backup[64] ^= 1u;
  if (interrupted) {
    g_fault_write_address = APP_BASE;
    g_fault_writes_remaining = -1;
  }
  bool reset = ota_delta_check_and_apply();
  if (scenario == 3) {
    return !reset && saved->phase == MOTA_ROLLBACK_READY && g_gpregret2 == 0xADu &&
           g_settings_writes == 0 && memcmp(FLASH + APP_BASE, base, base_len) == 0;
  }
  if (!reset) return false;
  if (interrupted) {
    if (saved->phase != MOTA_ROLLBACK_INSTALLING || g_bank0 != BANK_INVALID_APP_V) return false;
    g_fault_writes_remaining = 0;
  } else {
    if (saved->phase != MOTA_ROLLBACK_TRIAL || g_bank0 != BANK_VALID_APP_V ||
        memcmp(FLASH + APP_BASE, next, next_len) != 0) return false;
    cold_boot();
    if (scenario == 5) {
      if (!ota_delta_check_and_apply()) return false;
    } else {
      if (!ota_rollback_pending() || ota_delta_check_and_apply() ||
          saved->phase != MOTA_ROLLBACK_RUNNING || trial_watchdog_starts != 1) return false;
    }
    if (scenario == 0) {
      // The application confirms by programming the phase word once healthy.
      rollback_phase(page, MOTA_ROLLBACK_DONE);
      cold_boot();
      return !ota_rollback_pending() && !ota_delta_check_and_apply() &&
             g_bank0 == BANK_VALID_APP_V && memcmp(FLASH + APP_BASE, next, next_len) == 0;
    }
  }
  if (scenario != 5) {
    if (scenario == 4) backup[64] ^= 1u;
    cold_boot();
    if (!ota_rollback_pending() || !ota_delta_check_and_apply()) return false;
  }
  if (scenario == 4) {
    return saved->phase == MOTA_ROLLBACK_FAILED && g_bank0 == BANK_INVALID_APP_V &&
           g_gpregret2 == 0xADu && !ota_rollback_pending();
  }
  return saved->phase == MOTA_ROLLBACK_DONE && g_bank0 == BANK_VALID_APP_V &&
         g_gpregret2 == 0xACu && g_size == base_len &&
         memcmp(FLASH + APP_BASE, base, base_len) == 0 &&
         (sd ? no_nor() : g_sd_init_calls == 0 && g_qspi_source_marker == (int)medium);
}
#endif

int main(int argc, char **argv) {
  if (argc != 2) return 2;
  int scenario = atoi(argv[1]);
  uint8_t *base, *delta, *expected;
  uint32_t base_len = (uint32_t)load("vectors/base.img", &base);
  uint32_t delta_len = (uint32_t)load("vectors/delta.mota", &delta);
  uint32_t expected_len = (uint32_t)load("vectors/new.img", &expected);
  int ok = 1;
  prepare(base, base_len);

  if (scenario == 0 || scenario == 1) {
    uint8_t *image = expected, *package = delta;
    uint32_t image_len = expected_len, package_len = delta_len;
    if (scenario == 1) {
      image = make_large_image(&image_len);
      package = make_full_mota(image, image_len, &package_len);
    }
    ok = stage_external_mota(package, package_len);
    stage_nor(package, package_len);
    ok = ok && ota_delta_check_and_apply() && committed(image, image_len) &&
         no_nor() && external_io_ok() &&
         memcmp(&SD_AUTH, &(mota_sd_auth_t){0}, sizeof(SD_AUTH)) == 0;
    if (scenario == 1) { free(image); free(package); }
  } else if (scenario == 2) {
    // A valid internal/NOR candidate is a trap: explicit SD must never fall
    // through to either one when retained authorization is malformed.
    for (unsigned i = 0; i < 9; i++) {
      prepare(base, base_len);
      if (!stage_external_mota(delta, delta_len)) abort();
      stage_nor(delta, delta_len);
      stage_internal(delta, delta_len);
      switch (i) {
        case 0: memset(&SD_AUTH, 0, sizeof(SD_AUTH)); break;
        case 1: SD_AUTH.crc32 ^= 1u; break;
        case 2: SD_AUTH.purpose = MOTA_SD_AUTH_PURPOSE_BOOTLOADER; auth_crc(); break;
        case 3: SD_AUTH.format_ver = 3u; auth_crc(); break;
        case 4: SD_AUTH.reserved = 1u; auth_crc(); break;
        case 5: SD_AUTH.sector_count++; auth_crc(); break;
        case 6: SD_AUTH.first_sector = 0u; auth_crc(); break;
        case 7: SD_AUTH.length--; auth_crc(); break;
        default: SD_AUTH.version--; auth_crc(); break;
      }
      ok = ok && !ota_delta_check_and_apply() && no_app_write(base, base_len) &&
           no_nor() && g_sd_init_calls == 0 && g_sd_read_calls == 0 &&
           g_gpregret == 0 && g_gpregret2 == 0xBDu &&
           memcmp(&SD_AUTH, &(mota_sd_auth_t){0}, sizeof(SD_AUTH)) == 0;
      // Attempt a second boot with the same trigger but no new auth record.
      g_gpregret = GPREGRET_OTA_APPLY;
      g_gpregret2 = GPREGRET2_OTA_STAGE_SD;
      ok = ok && !ota_delta_check_and_apply() && no_app_write(base, base_len) &&
           no_nor() && g_sd_init_calls == 0;
    }
  } else if (scenario == 3) {
    ok = stage_external_mota(delta, delta_len);
    stage_nor(delta, delta_len);
    stage_internal(delta, delta_len);
    SD_AUTH.container_sha256[0] ^= 1u;
    auth_crc();
    ok = ok && !ota_delta_check_and_apply() && no_app_write(base, base_len) &&
         no_nor() && g_sd_init_calls == 1 && g_sd_read_calls > 0 &&
         g_gpregret2 == 0xBDu;
  } else if (scenario == 4) {
    const uint32_t markers[] = {GPREGRET2_OTA_STAGE_QSPI,
      GPREGRET2_OTA_STAGE_RAK15001, GPREGRET2_OTA_STAGE_HEADER_W25};
    for (unsigned i = 0; i < sizeof(markers) / sizeof(markers[0]); i++) {
      prepare(base, base_len);
      if (!stage_external_mota(delta, delta_len)) abort();
      mota_sd_auth_t saved = SD_AUTH;
      stage_nor(delta, delta_len);
      g_gpregret2 = markers[i];
      ok = ok && ota_delta_check_and_apply() && committed(expected, expected_len) &&
           g_sd_init_calls == 0 && g_sd_read_calls == 0 && g_sd_deinit_calls == 0 &&
           memcmp(&SD_AUTH, &saved, sizeof(saved)) == 0 &&
           g_qspi_init_calls == 1 && g_qspi_deinit_calls == 1 &&
           g_qspi_read_calls > 0 && g_qspi_write_calls > 0 &&
           g_qspi_source_marker == (int)markers[i];
    }
  } else if (scenario == 5) {
    // Legacy unknown hints retain the existing conservative internal-only
    // interpretation; they must not speculatively probe SD or NOR.
    const uint32_t markers[] = {GPREGRET2_OTA_STAGE_LEGACY, 0u, 0x55u, 0xFFu};
    for (unsigned i = 0; i < sizeof(markers) / sizeof(markers[0]); i++) {
      prepare(base, base_len);
      if (!stage_external_mota(delta, delta_len)) abort();
      mota_sd_auth_t saved = SD_AUTH;
      stage_nor(delta, delta_len);
      stage_internal(delta, delta_len);
      g_gpregret2 = markers[i];
      bool applied = ota_delta_check_and_apply();
      // This reused external-store fixture counts the deliberate approval
      // rewrite in the internal staging page as a pre-invalidation app write.
      // The dedicated readback fixture bounds the workspace separately and
      // checks that no actual application byte is modified while valid.
      int this_ok = applied && g_bank0 == BANK_VALID_APP_V && g_crc == 0x1234 &&
           g_size == expected_len && g_settings_writes == 2 &&
           g_gpregret == 0 && g_gpregret2 == 0xB8u &&
           memcmp(FLASH + MOTA_NRF52_APP_BASE, expected, expected_len) == 0 &&
           no_nor() && g_sd_init_calls == 0 && g_sd_deinit_calls == 0 &&
           memcmp(&SD_AUTH, &saved, sizeof(saved)) == 0;
      if (!this_ok) printf("internal marker=0x%X applied=%d result=0x%X settings=%d bank=%u\n",
                           markers[i], applied, g_gpregret2, g_settings_writes, g_bank0);
      ok = ok && this_ok;
    }
  } else if (scenario == 6) {
    ok = g_mota_bl_info.apply_abi == 3u && g_mota_bl_info.codec_mask == 5u &&
         g_mota_bl_info.storage_flags[0] == 0x0Au &&
         memcmp(g_mota_bl_info.storage_flags + 1, "\0\0\0", 3) == 0 &&
         g_mota_ram_capabilities.app.storage_flags == 0x14u &&
         sizeof(g_mota_rak_sd_info) == 16u &&
         memcmp(g_mota_rak_sd_info.magic, "MOTASDRA", 8u) == 0 &&
         g_mota_rak_sd_info.abi == 1u && g_mota_rak_sd_info.auth_len == 72u &&
         g_mota_rak_sd_info.storage_flags == 0x01u &&
         g_mota_rak_sd_info.stage_marker == GPREGRET2_OTA_STAGE_SD &&
         g_mota_rak_sd_info.reserved[0] == 0u && g_mota_rak_sd_info.reserved[1] == 0u;
#ifdef MOTA_ROLLBACK_HOST_TEST
  } else if (scenario >= 10 && scenario < 17) {
    const uint32_t media[] = {GPREGRET2_OTA_STAGE_SD, GPREGRET2_OTA_STAGE_RAK15001,
                              GPREGRET2_OTA_STAGE_QSPI, GPREGRET2_OTA_STAGE_HEADER_W25};
    for (unsigned i = 0; i < sizeof(media) / sizeof(media[0]); ++i) {
      for (unsigned expanded = 0; expanded < 2; ++expanded) {
        uint32_t page = expanded ? MOTA_ROLLBACK_EXPANDED_PAGE : MOTA_ROLLBACK_LEGACY_PAGE;
        rollback_armed_page = 0;
        if (!run_rollback(base, base_len, expected, expected_len, delta, delta_len,
                          media[i], page, scenario - 10)) {
          printf("rollback failed: medium=0x%X page=0x%X result=0x%X\n", media[i], page, g_gpregret2);
          ok = 0;
        }
      }
    }
#endif
  } else {
    ok = 0;
  }
  if (!ok) printf("scenario=%d result=0x%X settings=%d SD=%d/%d/%d NOR=%d/%d/%d selector=%d\n",
                  scenario, g_gpregret2, g_settings_writes, g_sd_init_calls,
                  g_sd_read_calls, g_sd_deinit_calls, g_qspi_init_calls,
                  g_qspi_read_calls, g_qspi_deinit_calls, g_qspi_source_marker);
  free(base); free(delta); free(expected);
  printf("RAK combined storage scenario %d: %s\n", scenario, ok ? "PASS" : "FAIL");
  return ok ? 0 : 1;
}
