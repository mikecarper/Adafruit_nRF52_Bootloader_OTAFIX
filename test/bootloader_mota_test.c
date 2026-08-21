// Host regression for the format-v3 app-preserving bootloader-update path.
// Exercises the real ota_delta.c parser, integrity gates, scratch copy, and
// GPREGRET lifecycle without touching hardware.
#include <stdbool.h>
#include <setjmp.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ota_layout.h"

#define FLASH_LEN        0x00100000u
#define QSPI_LEN         (2u * 1024u * 1024u)
#define MANIFEST_OFFSET  0x00009E00u
#define CAPS_OFFSET      0x00000300u
#define TEST_BLOCK_LOG2  10u

#if defined(MOTA_INTERNAL_BOOTLOADER_UPDATE)
  #define TEST_BOARD_ID       0x239A0029u
  #define TEST_OTHER_BOARD_ID 0x239A0071u
  #define TEST_DEVICE_NAME    "3401_DFU"
  #define TEST_HW_ID          "NRF_BL_239A0029_3401_DFU"
  #define TEST_TARGET_ID      0x23818A80u
  #define TEST_SOURCE         GPREGRET2_OTA_STAGE_EXPANDED
  #define TEST_PRESERVE_END   MOTA_NRF52_INTERNAL_BL_SLOT_START
  #define TEST_RAW_START      MOTA_NRF52_INTERNAL_BL_SLOT_START
  #define TEST_STORAGE_FLAGS  (MOTA_BL_STORAGE_STAGE_CEILING | MOTA_BL_STORAGE_BOOT_UPDATE)
#else
  #define TEST_BOARD_ID       0x28860044u
  #define TEST_OTHER_BOARD_ID 0x28860045u
  #define TEST_DEVICE_NAME    "XIAO_DFU"
  #define TEST_HW_ID          "XIAO_BL_28860044"
  #define TEST_TARGET_ID      TEST_BOARD_ID
  #define TEST_SOURCE         GPREGRET2_OTA_STAGE_QSPI
  #define TEST_PRESERVE_END   MOTA_NRF52_BL_SCRATCH_START
  #define TEST_RAW_START      MOTA_NRF52_BL_SCRATCH_START
  #define TEST_STORAGE_FLAGS  (MOTA_BL_STORAGE_STAGE_CEILING | MOTA_BL_STORAGE_QSPI | \
                              MOTA_BL_STORAGE_BOOT_UPDATE)
#endif

static uint8_t  FLASH[FLASH_LEN];
static uint8_t  QSPI[QSPI_LEN];
static uint8_t  APP_SNAPSHOT[TEST_PRESERVE_END - MOTA_NRF52_APP_BASE];
static uint8_t  OLD_BL_SNAPSHOT[MOTA_NRF52_BL_SIZE];
static uint32_t g_gpregret, g_gpregret2;
static int      g_qspi_init_calls, g_qspi_deinit_calls, g_qspi_writes;
static int      g_settings_writes, g_mbr_calls, g_mbr_success;
static uint32_t g_mbr_source, g_mbr_words, g_corrupt_write_address;
#if defined(MOTA_INTERNAL_BOOTLOADER_UPDATE)
static jmp_buf  g_power_cut_env;
static int      g_power_cut_armed, g_power_cut_after_page;
static int      g_compaction_started, g_raw_pages_written;
#endif

void otah_read(uint32_t address, void *dst, uint32_t len) {
  memcpy(dst, FLASH + address, len);
}
void otah_erase(uint32_t page) {
  memset(FLASH + page, 0xFF, MOTA_NRF52_FLASH_PAGE);
}
void otah_write_words(uint32_t address, const uint32_t *src, uint32_t words) {
  uint32_t *dst = (uint32_t *)(FLASH + address);
  for (uint32_t i = 0; i < words; i++) {
    dst[i] &= src[i];
  }
  if (address == g_corrupt_write_address) {
    FLASH[address] ^= 1u;
  }
#if defined(MOTA_INTERNAL_BOOTLOADER_UPDATE)
  // The approval-clear rewrite of the first slot page still begins with mOTA.
  // The first compacted raw page does not; from there writes are sequential.
  if (address == TEST_RAW_START && memcmp(src, "mOTA", 4u) != 0) {
    g_compaction_started = 1;
  }
  if (g_compaction_started &&
      address == TEST_RAW_START + (uint32_t)g_raw_pages_written * MOTA_NRF52_FLASH_PAGE) {
    g_raw_pages_written++;
    if (g_power_cut_armed && g_raw_pages_written == g_power_cut_after_page) {
      longjmp(g_power_cut_env, 1);
    }
  }
#endif
}
uint32_t otah_gpregret_get(void) {
  return g_gpregret;
}
void otah_gpregret_set(uint32_t value) {
  g_gpregret = value;
}
uint32_t otah_gpregret2_get(void) {
  return g_gpregret2;
}
void otah_gpregret2_set(uint32_t value) {
  g_gpregret2 = value;
}
uint16_t otah_crc16(uint32_t address, uint32_t len) {
  (void)address;
  (void)len;
  return 0x1234u;
}
void otah_settings_commit(uint16_t bank0, uint16_t crc, uint32_t size) {
  (void)bank0;
  (void)crc;
  (void)size;
  g_settings_writes++;
}

bool ota_qspi_init(void) {
  g_qspi_init_calls++;
  return true;
}
void ota_qspi_deinit(void) {
  g_qspi_deinit_calls++;
}
uint32_t ota_qspi_capacity(void) {
  return sizeof(QSPI);
}
bool ota_qspi_read(uint32_t offset, void *dst, uint32_t len) {
  if ((uint64_t)offset + len > sizeof(QSPI)) {
    return false;
  }
  memcpy(dst, QSPI + offset, len);
  return true;
}
bool ota_qspi_write(uint32_t offset, const void *src, uint32_t len) {
  if ((uint64_t)offset + len > sizeof(QSPI)) {
    return false;
  }
  g_qspi_writes++;
  const uint8_t *in = src;
  for (uint32_t i = 0; i < len; i++) {
    QSPI[offset + i] &= in[i];
  }
  return true;
}

const uint8_t *otah_flash_pointer(uint32_t address, uint32_t len) {
  return (uint64_t)address + len <= sizeof(FLASH) ? FLASH + address : NULL;
}
int otah_mbr_copy_bl(uint32_t source, uint32_t word_count) {
  g_mbr_calls++;
  g_mbr_source = source;
  g_mbr_words  = word_count;
  return g_mbr_success;
}

#include "ota_delta.c"

static void wr32(uint8_t *p, uint32_t value) {
  p[0] = (uint8_t)value;
  p[1] = (uint8_t)(value >> 8);
  p[2] = (uint8_t)(value >> 16);
  p[3] = (uint8_t)(value >> 24);
}
static void sha_bytes(const uint8_t *data, uint32_t len, uint8_t out[32]) {
  sha256_ctx_t ctx;
  sha256_init(&ctx);
  sha256_update(&ctx, data, len);
  sha256_final(&ctx, out);
}

static void fix_image_crc(uint8_t *image) {
  bootloader_update_manifest_t *m = (void *)(image + MANIFEST_OFFSET);
  m->crc32 = 0;
  m->crc32 = bootloader_image_crc32(image, MOTA_NRF52_BL_SIZE,
                                    MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32));
}

static uint8_t *make_boot_image(uint32_t board_id, uint16_t abi, uint8_t storage_flags) {
  uint8_t *image = malloc(MOTA_NRF52_BL_SIZE);
  if (!image) {
    exit(2);
  }
  for (uint32_t i = 0; i < MOTA_NRF52_BL_SIZE; i++) {
    image[i] = (uint8_t)(i * 29u + (i >> 7) + 0x35u);
  }
  wr32(image, 0x20040000u);
  wr32(image + 4, MOTA_NRF52_BL_START + 0x101u);

  mota_bl_info_t *caps = (void *)(image + CAPS_OFFSET);
  const uint8_t   magic[8] = {MOTA_BL_MAGIC0, MOTA_BL_MAGIC1, MOTA_BL_MAGIC2, MOTA_BL_MAGIC3,
                              MOTA_BL_MAGIC4, MOTA_BL_MAGIC5, MOTA_BL_MAGIC6, MOTA_BL_MAGIC7};
  memcpy(caps->magic, magic, sizeof(magic));
  caps->apply_abi        = abi;
  caps->codec_mask       = 1u;
  caps->storage_flags[0] = storage_flags;
  memset(caps->storage_flags + 1, 0, 3);

  bootloader_update_manifest_t *m = (void *)(image + MANIFEST_OFFSET);
  memset(m, 0, sizeof(*m));
  m->magic0      = BOOTLOADER_UPDATE_MANIFEST_MAGIC0;
  m->magic1      = BOOTLOADER_UPDATE_MANIFEST_MAGIC1;
  m->version     = BOOTLOADER_UPDATE_MANIFEST_VERSION;
  m->header_size = sizeof(*m);
  m->image_start = MOTA_NRF52_BL_START;
  m->image_size  = MOTA_NRF52_BL_SIZE;
  m->board_id    = board_id;
  memcpy(m->device_name, TEST_DEVICE_NAME, sizeof(TEST_DEVICE_NAME) - 1u);
  fix_image_crc(image);
  return image;
}

static uint8_t *make_mota(const uint8_t *image, uint32_t image_len, uint8_t format_ver, uint8_t flags,
                          uint32_t target_id, const char *hw_id, uint32_t *total_out) {
  const uint32_t block_size     = 1u << TEST_BLOCK_LOG2;
  const uint32_t block_count    = (image_len + block_size - 1u) / block_size;
  const uint32_t leaves_len     = block_count * 4u;
  const uint32_t payload_offset = 8u + MOTA_MFL + leaves_len;
  const uint32_t total          = payload_offset + image_len + sizeof(TRAILER);
  uint8_t       *mota           = calloc(1, total);
  uint8_t       *level          = malloc(leaves_len);
  if (!mota || !level) {
    exit(2);
  }
  memcpy(mota, MAGIC, sizeof(MAGIC));
  wr32(mota + 4, total);
  uint8_t *manifest = mota + 8;
  manifest[0]       = format_ver;
  manifest[1]       = flags;
  manifest[2]       = 0x12u;
  wr32(manifest + 3, target_id);
  wr32(manifest + 7, 0x02040100u);
  wr32(manifest + 11, image_len);
  wr32(manifest + 15, image_len);
  manifest[19] = TEST_BLOCK_LOG2;
  manifest[56] = CODEC_FULL;
  size_t hw_len = strlen(hw_id);
  if (hw_len > 32) {
    hw_len = 32;
  }
  memcpy(manifest + 57, hw_id, hw_len);
  memset(manifest + 97, 0xA5, 32);
  memset(manifest + 129, 0x5A, 64);
  memcpy(manifest + 193, APRV, sizeof(APRV));

  uint8_t hash[32];
  sha_bytes(image, image_len, hash);
  memcpy(manifest + 24, hash, sizeof(hash));
  for (uint32_t i = 0; i < block_count; i++) {
    uint32_t off = i * block_size;
    uint32_t len = image_len - off;
    if (len > block_size) {
      len = block_size;
    }
    sha_bytes(image + off, len, hash);
    memcpy(level + i * 4u, hash, 4);
    memcpy(manifest + MOTA_MFL + i * 4u, hash, 4);
  }
  uint32_t count = block_count;
  while (count > 1) {
    uint32_t next = 0;
    for (uint32_t i = 0; i < count; i += 2) {
      if (i + 1u < count) {
        uint8_t pair[8];
        memcpy(pair, level + i * 4u, sizeof(pair));
        sha_bytes(pair, sizeof(pair), hash);
        memcpy(level + next * 4u, hash, 4);
      } else {
        memcpy(level + next * 4u, level + i * 4u, 4);
      }
      next++;
    }
    count = next;
  }
  memcpy(manifest + 20, level, 4);
  free(level);
  memcpy(mota + payload_offset, image, image_len);
  memcpy(mota + total - sizeof(TRAILER), TRAILER, sizeof(TRAILER));
  *total_out = total;
  return mota;
}

static int app_unchanged(void) {
  return memcmp(FLASH + MOTA_NRF52_APP_BASE, APP_SNAPSHOT, sizeof(APP_SNAPSHOT)) == 0;
}

static int old_bootloader_unchanged(void) {
  return memcmp(FLASH + MOTA_NRF52_BL_START, OLD_BL_SNAPSHOT, sizeof(OLD_BL_SNAPSHOT)) == 0;
}

static void install_valid_endf(uint32_t endf_addr) {
  const uint32_t body_len = endf_addr - MOTA_NRF52_APP_BASE;
  uint8_t        body_hash[32];
  sha_bytes(FLASH + MOTA_NRF52_APP_BASE, body_len, body_hash);
  memset(FLASH + endf_addr, 0, ENDF_LEN);
  memcpy(FLASH + endf_addr, ENDF, sizeof(ENDF));
  wr32(FLASH + endf_addr + 4u, body_len);
  memcpy(FLASH + endf_addr + 8u, body_hash, 8u);
}

static void reset_device(void) {
  memset(FLASH, 0xFF, sizeof(FLASH));
  for (uint32_t a = MOTA_NRF52_APP_BASE; a < TEST_PRESERVE_END; a++) {
    FLASH[a] = (uint8_t)(a * 13u + 7u);
  }
  // Give the internal path an independently hash-valid live EndF with a full
  // page of free space before the shared slot.
  install_valid_endf(TEST_PRESERVE_END - MOTA_NRF52_FLASH_PAGE);
  memcpy(APP_SNAPSHOT, FLASH + MOTA_NRF52_APP_BASE, sizeof(APP_SNAPSHOT));
  for (uint32_t a = MOTA_NRF52_BL_START; a < MOTA_NRF52_BL_START + MOTA_NRF52_BL_SIZE; a++) {
    FLASH[a] = (uint8_t)(a * 7u + 0x5Bu);
  }
  memcpy(OLD_BL_SNAPSHOT, FLASH + MOTA_NRF52_BL_START, sizeof(OLD_BL_SNAPSHOT));
  memset(QSPI, 0xFF, sizeof(QSPI));
  g_gpregret              = GPREGRET_BOOTLOADER_APPLY;
  g_gpregret2             = TEST_SOURCE;
  g_qspi_init_calls       = 0;
  g_qspi_deinit_calls     = 0;
  g_qspi_writes           = 0;
  g_settings_writes       = 0;
  g_mbr_calls             = 0;
  g_mbr_success           = 0;
  g_mbr_source            = 0;
  g_mbr_words             = 0;
  g_corrupt_write_address = UINT32_MAX;
#if defined(MOTA_INTERNAL_BOOTLOADER_UPDATE)
  g_power_cut_armed       = 0;
  g_power_cut_after_page  = 0;
  g_compaction_started    = 0;
  g_raw_pages_written     = 0;
#endif
  g_cache_page            = 0;
  g_cache_dirty           = 0;
#if defined(MOTA_QSPI_FLASH)
  g_qspi_source     = 0;
  g_qspi_total_size = 0;
#endif
}

static void stage(const uint8_t *mota, uint32_t total) {
#if defined(MOTA_INTERNAL_BOOTLOADER_UPDATE)
  if (total > MOTA_NRF52_INTERNAL_BL_SLOT_END - MOTA_NRF52_INTERNAL_BL_SLOT_START) {
    fprintf(stderr, "test container too large\n");
    exit(2);
  }
  memcpy(FLASH + MOTA_NRF52_INTERNAL_BL_SLOT_START, mota, total);
#else
  if (total > sizeof(QSPI)) {
    fprintf(stderr, "test container too large\n");
    exit(2);
  }
  memcpy(QSPI, mota, total);
#endif
}

static int rejected_with(uint8_t *mota, uint32_t total, uint32_t result) {
  reset_device();
  stage(mota, total);
  bool applied = ota_delta_check_and_apply();
  return !applied && g_gpregret == 0 && g_gpregret2 == result && g_mbr_calls == 0 &&
         g_settings_writes == 0 && app_unchanged() && old_bootloader_unchanged();
}

static void report(const char *name, int ok, int *failures) {
  printf("%-66s %s\n", name, ok ? "PASS" : "FAIL");
  if (!ok) {
    (*failures)++;
  }
}

int main(void) {
  const uint32_t board_base    = TEST_BOARD_ID;
  const uint32_t board_other   = TEST_OTHER_BOARD_ID;
  const uint8_t  required_caps = TEST_STORAGE_FLAGS;
  int            failures = 0;
  uint32_t       total;

  uint8_t *image = make_boot_image(board_base, 3, required_caps);
  uint8_t *mota  = make_mota(image, MOTA_NRF52_BL_SIZE, 3,
                             MFLAG_FULL | MFLAG_SIGNED | MFLAG_BOOTLOADER,
                             TEST_TARGET_ID, TEST_HW_ID, &total);

  reset_device();
  stage(mota, total);
  g_mbr_success = 1;
  bool applied  = ota_delta_check_and_apply();
  int  ok       = applied && g_gpregret == 0 && g_gpregret2 == GPREGRET2_BL_MBR_HANDOFF &&
           g_mbr_calls == 1 && g_mbr_source == TEST_RAW_START &&
           g_mbr_words == MOTA_NRF52_BL_SIZE / 4u &&
#if defined(MOTA_INTERNAL_BOOTLOADER_UPDATE)
           g_qspi_init_calls == 0 && g_qspi_deinit_calls == 0 && g_qspi_writes == 0 &&
#else
           g_qspi_init_calls == 1 && g_qspi_deinit_calls == 1 && g_qspi_writes == 1 &&
#endif
           g_settings_writes == 0 &&
           memcmp(FLASH + TEST_RAW_START, image, MOTA_NRF52_BL_SIZE) == 0 && app_unchanged() &&
           old_bootloader_unchanged();
  report("valid v3 package produces raw source and reaches MBR with C8", ok, &failures);

  int calls_before = g_mbr_calls;
  applied          = ota_delta_check_and_apply();
  report("normal post-MBR boot preserves C8 and does not retry", !applied && g_gpregret2 == GPREGRET2_BL_MBR_HANDOFF &&
           g_mbr_calls == calls_before, &failures);

  reset_device();
  stage(mota, total);
#if defined(MOTA_INTERNAL_BOOTLOADER_UPDATE)
  g_gpregret2 = GPREGRET2_OTA_STAGE_QSPI;
#else
  g_gpregret2 = GPREGRET2_OTA_STAGE_EXPANDED;
#endif
  applied = ota_delta_check_and_apply();
  report("wrong bootloader staging backend is rejected", !applied && g_gpregret2 == GPREGRET2_BL_CONTAINER &&
           g_mbr_calls == 0 && app_unchanged(), &failures);

#if defined(MOTA_INTERNAL_BOOTLOADER_UPDATE)
  reset_device();
  report("manual UF2 fixed scratch guard rejects an app extending past E0000",
         ota_delta_live_app_fits_below(MOTA_NRF52_INTERNAL_BL_SLOT_START) &&
           !ota_delta_live_app_fits_below(MOTA_NRF52_BL_SCRATCH_START),
         &failures);

  reset_device();
  memset(FLASH + MOTA_NRF52_INTERNAL_BL_SLOT_START, 0xFF,
         MOTA_NRF52_INTERNAL_BL_SLOT_END - MOTA_NRF52_INTERNAL_BL_SLOT_START);
  memcpy(FLASH + MOTA_NRF52_INTERNAL_BL_SLOT_START + MOTA_NRF52_FLASH_PAGE, mota, total);
  applied = ota_delta_check_and_apply();
  report("shifted internal container is rejected", !applied && g_gpregret2 == GPREGRET2_BL_CONTAINER &&
           g_mbr_calls == 0 && app_unchanged(), &failures);

  // A marker whose inclusive EndF trailer crosses into the shared slot is not
  // enough free space. Remove the normal lower marker, install only that
  // crossing trailer, and require refusal before compaction/MBR.
  reset_device();
  const uint32_t safe_endf = TEST_PRESERVE_END - MOTA_NRF52_FLASH_PAGE;
  for (uint32_t a = safe_endf; a < safe_endf + ENDF_LEN; a++) {
    FLASH[a] = (uint8_t)(a * 13u + 7u);
  }
  install_valid_endf(TEST_PRESERVE_END - 32u);
  memcpy(APP_SNAPSHOT, FLASH + MOTA_NRF52_APP_BASE, sizeof(APP_SNAPSHOT));
  stage(mota, total);
  applied = ota_delta_check_and_apply();
  report("live EndF crossing shared slot is rejected before compaction",
         !applied && g_gpregret2 == GPREGRET2_BL_POLICY && g_raw_pages_written == 0 &&
           g_mbr_calls == 0 && g_settings_writes == 0 && app_unchanged() && old_bootloader_unchanged(),
         &failures);

  reset_device();
  FLASH[safe_endf + 8u] ^= 1u; // break EndF's body-hash anchor
  memcpy(APP_SNAPSHOT, FLASH + MOTA_NRF52_APP_BASE, sizeof(APP_SNAPSHOT));
  stage(mota, total);
  applied = ota_delta_check_and_apply();
  report("live EndF with wrong body hash is rejected before compaction",
         !applied && g_gpregret2 == GPREGRET2_BL_POLICY && g_raw_pages_written == 0 &&
           g_mbr_calls == 0 && g_settings_writes == 0 && app_unchanged() && old_bootloader_unchanged(),
         &failures);

  // Simulate loss of power immediately after programming each successive raw
  // destination page. The package may be partial, but neither application,
  // installed bootloader, nor settings can change before the Nordic MBR.
  int power_cut_ok = 1;
  for (int cut_page = 1; cut_page <= (int)(MOTA_NRF52_BL_SIZE / MOTA_NRF52_FLASH_PAGE); cut_page++) {
    reset_device();
    stage(mota, total);
    g_power_cut_after_page = cut_page;
    g_power_cut_armed      = 1;
    if (setjmp(g_power_cut_env) == 0) {
      (void)ota_delta_check_and_apply();
      power_cut_ok = 0; // every selected boundary must interrupt the call
    } else {
      g_power_cut_armed = 0;
      if (g_raw_pages_written != cut_page || g_gpregret != 0 || g_mbr_calls != 0 ||
          g_settings_writes != 0 || !app_unchanged() || !old_bootloader_unchanged()) {
        power_cut_ok = 0;
      }
      // Model reset-cleared RAM and prove the consumed trigger cannot retry a
      // half-compacted package.
      g_cache_page  = 0;
      g_cache_dirty = 0;
      int calls_before_reset = g_mbr_calls;
      if (ota_delta_check_and_apply() || g_mbr_calls != calls_before_reset ||
          !app_unchanged() || !old_bootloader_unchanged()) {
        power_cut_ok = 0;
      }
    }
  }
  report("power cut after every compacted page preserves app/old BL and cannot retry",
         power_cut_ok, &failures);
#endif

  uint8_t *wrong_image = make_boot_image(board_other, 3, required_caps);
  uint8_t *wrong = make_mota(wrong_image, MOTA_NRF52_BL_SIZE, 3,
                             MFLAG_FULL | MFLAG_SIGNED | MFLAG_BOOTLOADER,
                             board_other, "NRF_BL_WRONG_IDENTITY", &total);
  report("different target/image is rejected by exact identity", rejected_with(wrong, total, GPREGRET2_BL_POLICY),
         &failures);
  free(wrong);
  free(wrong_image);

  uint8_t *bad = make_mota(image, MOTA_NRF52_BL_SIZE, 3, MFLAG_FULL | MFLAG_BOOTLOADER,
                           TEST_TARGET_ID, TEST_HW_ID, &total);
  report("unsigned package is rejected", rejected_with(bad, total, GPREGRET2_BL_POLICY), &failures);
  free(bad);
  bad = make_mota(image, MOTA_NRF52_BL_SIZE, 3, MFLAG_FULL | MFLAG_SIGNED,
                  TEST_TARGET_ID, TEST_HW_ID, &total);
  report("non-bootloader kind is rejected", rejected_with(bad, total, GPREGRET2_BL_POLICY), &failures);
  free(bad);
  bad = make_mota(image, MOTA_NRF52_BL_SIZE, 2, MFLAG_FULL | MFLAG_SIGNED | MFLAG_BOOTLOADER,
                  TEST_TARGET_ID, TEST_HW_ID, &total);
  report("format-v2 bootloader package is rejected", rejected_with(bad, total, GPREGRET2_BL_POLICY), &failures);
  free(bad);
  bad = make_mota(image, MOTA_NRF52_BL_SIZE, 3, MFLAG_FULL | MFLAG_SIGNED | MFLAG_BOOTLOADER,
                  TEST_TARGET_ID, TEST_HW_ID, &total);
  memset(bad + 8u + 7u, 0, 4);
  report("zero firmware version is rejected", rejected_with(bad, total, GPREGRET2_BL_POLICY), &failures);
  free(bad);

  bad = make_mota(image, MOTA_NRF52_BL_SIZE, 3, MFLAG_FULL | MFLAG_SIGNED | MFLAG_BOOTLOADER,
                  TEST_TARGET_ID, TEST_HW_ID, &total);
  bad[8u + 24u] ^= 1u;
  report("bad payload image hash is rejected", rejected_with(bad, total, GPREGRET2_BL_INTEGRITY), &failures);
  free(bad);

  uint8_t *bad_image = make_boot_image(board_base, 3, required_caps);
  ((bootloader_update_manifest_t *)(bad_image + MANIFEST_OFFSET))->crc32 ^= 1u;
  bad = make_mota(bad_image, MOTA_NRF52_BL_SIZE, 3, MFLAG_FULL | MFLAG_SIGNED | MFLAG_BOOTLOADER,
                  TEST_TARGET_ID, TEST_HW_ID, &total);
  report("bad embedded manifest CRC is rejected", rejected_with(bad, total, GPREGRET2_BL_MANIFEST), &failures);
  free(bad);
  free(bad_image);

  bad_image = make_boot_image(board_base, 2, required_caps & (uint8_t)~MOTA_BL_STORAGE_BOOT_UPDATE);
  fix_image_crc(bad_image);
  bad = make_mota(bad_image, MOTA_NRF52_BL_SIZE, 3, MFLAG_FULL | MFLAG_SIGNED | MFLAG_BOOTLOADER,
                  TEST_TARGET_ID, TEST_HW_ID, &total);
  report("image that removes ABI3/boot-update capability is rejected", rejected_with(bad, total, GPREGRET2_BL_MANIFEST),
         &failures);
  free(bad);
  free(bad_image);

  bad_image = make_boot_image(board_base, 3, required_caps);
  ((mota_bl_info_t *)(bad_image + CAPS_OFFSET))->codec_mask = 0;
  fix_image_crc(bad_image);
  bad = make_mota(bad_image, MOTA_NRF52_BL_SIZE, 3, MFLAG_FULL | MFLAG_SIGNED | MFLAG_BOOTLOADER,
                  TEST_TARGET_ID, TEST_HW_ID, &total);
  report("image that removes full-codec capability is rejected", rejected_with(bad, total, GPREGRET2_BL_MANIFEST),
         &failures);
  free(bad);
  free(bad_image);

  bad_image = make_boot_image(board_base, UINT16_MAX, required_caps);
  fix_image_crc(bad_image);
  bad = make_mota(bad_image, MOTA_NRF52_BL_SIZE, 3, MFLAG_FULL | MFLAG_SIGNED | MFLAG_BOOTLOADER,
                  TEST_TARGET_ID, TEST_HW_ID, &total);
  report("image with erased-value capability ABI is rejected", rejected_with(bad, total, GPREGRET2_BL_MANIFEST),
         &failures);
  free(bad);
  free(bad_image);

  bad_image = make_boot_image(board_base, 3, required_caps | 0x80u);
  fix_image_crc(bad_image);
  bad = make_mota(bad_image, MOTA_NRF52_BL_SIZE, 3, MFLAG_FULL | MFLAG_SIGNED | MFLAG_BOOTLOADER,
                  TEST_TARGET_ID, TEST_HW_ID, &total);
  report("image with unknown capability storage bit is rejected", rejected_with(bad, total, GPREGRET2_BL_MANIFEST),
         &failures);
  free(bad);
  free(bad_image);

  bad_image = make_boot_image(board_base, 3, required_caps);
  ((mota_bl_info_t *)(bad_image + CAPS_OFFSET))->storage_flags[2] = 1u;
  fix_image_crc(bad_image);
  bad = make_mota(bad_image, MOTA_NRF52_BL_SIZE, 3, MFLAG_FULL | MFLAG_SIGNED | MFLAG_BOOTLOADER,
                  TEST_TARGET_ID, TEST_HW_ID, &total);
  report("image with nonzero capability reserved byte is rejected", rejected_with(bad, total, GPREGRET2_BL_MANIFEST),
         &failures);
  free(bad);
  free(bad_image);

  bad_image = make_boot_image(board_base, 3, required_caps);
  memcpy(bad_image + CAPS_OFFSET + sizeof(mota_bl_info_t), bad_image + CAPS_OFFSET,
         sizeof(mota_bl_info_t));
  fix_image_crc(bad_image);
  bad = make_mota(bad_image, MOTA_NRF52_BL_SIZE, 3, MFLAG_FULL | MFLAG_SIGNED | MFLAG_BOOTLOADER,
                  TEST_TARGET_ID, TEST_HW_ID, &total);
  report("image with duplicate valid capability markers is rejected",
         rejected_with(bad, total, GPREGRET2_BL_MANIFEST), &failures);
  free(bad);
  free(bad_image);

  bad_image = make_boot_image(board_base, 3, required_caps);
  memcpy(bad_image + CAPS_OFFSET - sizeof(mota_bl_info_t), bad_image + CAPS_OFFSET,
         sizeof(mota_bl_info_t));
  ((mota_bl_info_t *)(bad_image + CAPS_OFFSET - sizeof(mota_bl_info_t)))->apply_abi = 2u;
  fix_image_crc(bad_image);
  bad = make_mota(bad_image, MOTA_NRF52_BL_SIZE, 3, MFLAG_FULL | MFLAG_SIGNED | MFLAG_BOOTLOADER,
                  TEST_TARGET_ID, TEST_HW_ID, &total);
  reset_device();
  stage(bad, total);
  g_mbr_success = 1;
  applied = ota_delta_check_and_apply();
  const int decoy_accepted =
    applied && g_gpregret2 == GPREGRET2_BL_MBR_HANDOFF && g_mbr_calls == 1 && app_unchanged();
  if (!decoy_accepted) {
    printf("  decoy diagnostics: applied=%d result=0x%02X mbr=%d app=%d\n",
           applied, g_gpregret2, g_mbr_calls, app_unchanged());
  }
  report("invalid capability decoy before the unique valid marker is accepted",
         decoy_accepted, &failures);
  free(bad);
  free(bad_image);

  bad_image = make_boot_image(board_base, 3, required_caps);
  wr32(bad_image, 0xFFFFFFFFu);
  fix_image_crc(bad_image);
  bad = make_mota(bad_image, MOTA_NRF52_BL_SIZE, 3, MFLAG_FULL | MFLAG_SIGNED | MFLAG_BOOTLOADER,
                  TEST_TARGET_ID, TEST_HW_ID, &total);
  report("invalid vector table is rejected before scratch erase", rejected_with(bad, total, GPREGRET2_BL_INTEGRITY),
         &failures);
  free(bad);
  free(bad_image);

  reset_device();
  stage(mota, total);
  g_corrupt_write_address = TEST_RAW_START + MOTA_NRF52_FLASH_PAGE;
  applied                 = ota_delta_check_and_apply();
  ok = !applied && g_gpregret2 == GPREGRET2_BL_COPY && g_mbr_calls == 0 && app_unchanged();
  int writes_before = g_qspi_writes;
  applied           = ota_delta_check_and_apply();
  ok = ok && !applied && g_gpregret2 == GPREGRET2_BL_COPY && g_qspi_writes == writes_before;
  report("scratch readback fault is fail-closed and a reset does not retry", ok, &failures);

  reset_device();
  stage(mota, total);
  applied = ota_delta_check_and_apply();
  report("returned/failed MBR call records C9 and preserves application", !applied && g_gpregret2 == GPREGRET2_BL_MBR_RETURNED &&
           g_mbr_calls == 1 && app_unchanged(), &failures);

  reset_device();
  stage(mota, total);
  g_gpregret  = GPREGRET_OTA_APPLY;
#if defined(MOTA_INTERNAL_BOOTLOADER_UPDATE)
  g_gpregret2 = GPREGRET2_OTA_STAGE_EXPANDED;
#else
  g_gpregret2 = TEST_SOURCE;
#endif
  applied     = ota_delta_check_and_apply();
  report("ordinary app trigger rejects format-v3/bootloader payload", !applied && g_gpregret2 == 0xB3u &&
           g_mbr_calls == 0
           && app_unchanged()
         , &failures);

#if !defined(MOTA_INTERNAL_BOOTLOADER_UPDATE)
  uint32_t too_large_len = MOTA_NRF52_BL_SCRATCH_START - MOTA_NRF52_APP_BASE + 1u;
  uint8_t *too_large = malloc(too_large_len);
  memset(too_large, 0xA6, too_large_len);
  bad = make_mota(too_large, too_large_len, 2, MFLAG_FULL, 0x12345678u, "APP_TEST", &total);
  reset_device();
  stage(bad, total);
  g_gpregret  = GPREGRET_OTA_APPLY;
  g_gpregret2 = GPREGRET2_OTA_STAGE_QSPI;
  applied     = ota_delta_check_and_apply();
  report("ordinary full app cannot cross reserved 0xE0000 scratch", !applied && g_gpregret2 == 0xB3u &&
           g_settings_writes == 0 && app_unchanged(), &failures);
  free(bad);
  free(too_large);
#endif

  free(mota);
  free(image);
  printf("\n%s (%d failure%s)\n", failures ? "SUITE FAILED" : "SUITE PASSED", failures,
         failures == 1 ? "" : "s");
  return failures ? 1 : 0;
}
