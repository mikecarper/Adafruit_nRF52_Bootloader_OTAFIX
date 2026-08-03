// Host simulation for the MeshTower V2 SD-backed self-update path.
//
// This runs the real ota_delta_check_and_apply() entry point against simulated
// nRF52840 flash and a raw-sector SD card. It covers both supported package
// types:
//   - a full image larger than the legacy 0x98000 internal-staging limit;
//   - the committed detools in-place delta vector.
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ota_layout.h"
#include "ota_sd_handoff.h"

#define FLASH_LEN          MOTA_NRF52_APP_END
#define SD_CARD_SECTORS    4096u
#define SD_FIRST_SECTOR    2048u
#define LARGE_IMAGE_LEN    0x0009A000u

static const char TEST_HW_ID[] = "Heltec_tower_v2_sdcard";
static uint8_t FLASH[FLASH_LEN];
static uint8_t SD_CARD[SD_CARD_SECTORS * MOTA_SD_SECTOR_SIZE];
static uint32_t g_gpregret;
static uint16_t g_bank0;
static uint16_t g_crc;
static uint32_t g_size;
static int g_settings_writes;
static int g_app_write_while_valid;
static int g_sd_init_calls;
static int g_sd_deinit_calls;
static int g_sd_read_calls;

void otah_read(uint32_t address, void* dst, uint32_t len) {
  memcpy(dst, FLASH + address, len);
}

void otah_erase(uint32_t page) {
  if (page >= MOTA_NRF52_APP_BASE && page < MOTA_NRF52_APP_END && g_bank0 != 0xFFu) {
    g_app_write_while_valid++;
  }
  memset(FLASH + page, 0xFF, MOTA_NRF52_FLASH_PAGE);
}

void otah_write_words(uint32_t address, const uint32_t* src, uint32_t word_count) {
  if (address >= MOTA_NRF52_APP_BASE && address < MOTA_NRF52_APP_END && g_bank0 != 0xFFu) {
    g_app_write_while_valid++;
  }
  uint32_t* dst = (uint32_t*)(FLASH + address);
  for (uint32_t i = 0; i < word_count; i++) dst[i] &= src[i];
}

uint32_t otah_gpregret_get(void) { return g_gpregret; }
void otah_gpregret_set(uint32_t value) { g_gpregret = value; }
uint16_t otah_crc16(uint32_t address, uint32_t len) {
  (void)address;
  (void)len;
  return 0x1234;
}

void otah_settings_commit(uint16_t bank0, uint16_t crc, uint32_t size) {
  g_bank0 = bank0;
  g_crc = crc;
  g_size = size;
  g_settings_writes++;
}

bool ota_sd_init(void) {
  g_sd_init_calls++;
  return true;
}

void ota_sd_deinit(void) { g_sd_deinit_calls++; }

bool ota_sd_read_sector(uint32_t sector, uint8_t out[MOTA_SD_SECTOR_SIZE]) {
  g_sd_read_calls++;
  if (sector >= SD_CARD_SECTORS) return false;
  memcpy(out, SD_CARD + sector * MOTA_SD_SECTOR_SIZE, MOTA_SD_SECTOR_SIZE);
  return true;
}

bool ota_sd_read_bytes(uint32_t first_sector, uint32_t offset, void* out, uint32_t len) {
  uint8_t sector[MOTA_SD_SECTOR_SIZE];
  uint8_t* dst = (uint8_t*)out;
  while (len) {
    uint32_t sector_offset = offset & (MOTA_SD_SECTOR_SIZE - 1u);
    uint32_t chunk = MOTA_SD_SECTOR_SIZE - sector_offset;
    if (chunk > len) chunk = len;
    uint32_t lba = first_sector + offset / MOTA_SD_SECTOR_SIZE;
    if (lba < first_sector || !ota_sd_read_sector(lba, sector)) return false;
    memcpy(dst, sector + sector_offset, chunk);
    dst += chunk;
    offset += chunk;
    len -= chunk;
  }
  return true;
}

#include "ota_delta.c"

static void wr32(uint8_t* p, uint32_t value) {
  p[0] = (uint8_t)value;
  p[1] = (uint8_t)(value >> 8);
  p[2] = (uint8_t)(value >> 16);
  p[3] = (uint8_t)(value >> 24);
}

static long load(const char* path, uint8_t** out) {
  FILE* file = fopen(path, "rb");
  if (!file) {
    fprintf(stderr, "cannot open %s\n", path);
    exit(2);
  }
  fseek(file, 0, SEEK_END);
  long len = ftell(file);
  fseek(file, 0, SEEK_SET);
  *out = malloc((size_t)len);
  if (!*out || fread(*out, 1, (size_t)len, file) != (size_t)len) {
    fprintf(stderr, "cannot read %s\n", path);
    fclose(file);
    exit(2);
  }
  fclose(file);
  return len;
}

static void sha256_bytes(const uint8_t* data, uint32_t len, uint8_t out[32]) {
  sha256_ctx_t ctx;
  sha256_init(&ctx);
  sha256_update(&ctx, data, len);
  sha256_final(&ctx, out);
}

static uint8_t* make_large_image(uint32_t* len_out) {
  uint8_t* image = malloc(LARGE_IMAGE_LEN);
  if (!image) exit(2);
  const uint32_t body_len = LARGE_IMAGE_LEN - ENDF_LEN;
  for (uint32_t i = 0; i < body_len; i++) {
    image[i] = (uint8_t)((i * 37u) ^ (i >> 8) ^ 0x5Au);
  }

  uint8_t* endf = image + body_len;
  uint8_t body_hash[32];
  memset(endf, 0, ENDF_LEN);
  sha256_bytes(image, body_len, body_hash);
  memcpy(endf, "EndF", 4);
  wr32(endf + 4, body_len);
  memcpy(endf + 8, body_hash, 8);
  wr32(endf + 16, 0x01100800u);
  wr32(endf + 20, 0x12345678u);
  memcpy(endf + 24, TEST_HW_ID, sizeof(TEST_HW_ID) - 1u);
  *len_out = LARGE_IMAGE_LEN;
  return image;
}

static uint8_t* make_full_mota(const uint8_t* image, uint32_t image_len,
                               uint32_t* total_out) {
  const uint32_t block_size = 1024u;
  const uint32_t leaf_count = (image_len + block_size - 1u) / block_size;
  const uint32_t leaves_len = leaf_count * 4u;
  const uint32_t payload_offset = 8u + MOTA_MFL + leaves_len;
  const uint32_t total = payload_offset + image_len + sizeof(TRAILER);
  uint8_t* mota = calloc(1, total);
  uint8_t* level = malloc(leaves_len);
  if (!mota || !level) exit(2);

  memcpy(mota, "mOTA", 4);
  wr32(mota + 4, total);
  uint8_t* manifest = mota + 8;
  manifest[0] = 2;
  manifest[1] = MFLAG_FULL;
  manifest[2] = 0x12;
  wr32(manifest + 11, image_len);
  wr32(manifest + 15, image_len);
  manifest[19] = 10;
  manifest[56] = CODEC_FULL;
  memcpy(manifest + 57, TEST_HW_ID, sizeof(TEST_HW_ID) - 1u);
  memcpy(manifest + 193, APRV, sizeof(APRV));

  uint8_t image_hash[32];
  sha256_bytes(image, image_len, image_hash);
  memcpy(manifest + 24, image_hash, sizeof(image_hash));

  for (uint32_t i = 0; i < leaf_count; i++) {
    uint32_t offset = i * block_size;
    uint32_t chunk = image_len - offset;
    uint8_t hash[32];
    if (chunk > block_size) chunk = block_size;
    sha256_bytes(image + offset, chunk, hash);
    memcpy(level + i * 4u, hash, 4);
    memcpy(manifest + MOTA_MFL + i * 4u, hash, 4);
  }

  uint32_t count = leaf_count;
  while (count > 1) {
    uint32_t next = 0;
    for (uint32_t i = 0; i < count; i += 2) {
      if (i + 1 < count) {
        uint8_t pair[8];
        uint8_t hash[32];
        memcpy(pair, level + i * 4u, 8);
        sha256_bytes(pair, sizeof(pair), hash);
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

static void reset_device(const uint8_t* base, uint32_t base_len) {
  memset(FLASH, 0xFF, sizeof(FLASH));
  if (base && base_len) memcpy(FLASH + MOTA_NRF52_APP_BASE, base, base_len);
  memset(SD_CARD, 0xFF, sizeof(SD_CARD));
  g_gpregret = GPREGRET_OTA_APPLY;
  g_bank0 = BANK_VALID_APP_V;
  g_crc = 0;
  g_size = base_len;
  g_settings_writes = 0;
  g_app_write_while_valid = 0;
  g_sd_init_calls = 0;
  g_sd_deinit_calls = 0;
  g_sd_read_calls = 0;
  g_cache_page = 0;
  g_cache_dirty = 0;
}

static int stage_sd_mota(const uint8_t* mota, uint32_t total) {
  const uint32_t sectors = (total + MOTA_SD_SECTOR_SIZE - 1u) / MOTA_SD_SECTOR_SIZE;
  if (SD_FIRST_SECTOR + sectors > SD_CARD_SECTORS) return 0;
  memcpy(SD_CARD + SD_FIRST_SECTOR * MOTA_SD_SECTOR_SIZE, mota, total);
  memcpy(SD_CARD + SD_FIRST_SECTOR * MOTA_SD_SECTOR_SIZE + 8u + 193u,
         APRV, sizeof(APRV));

  uint8_t* handoff = SD_CARD + MOTA_SD_HANDOFF_SECTOR * MOTA_SD_SECTOR_SIZE;
  memset(handoff, 0xFF, MOTA_SD_SECTOR_SIZE);
  memcpy(handoff, MOTA_SD_HANDOFF_MAGIC, sizeof(MOTA_SD_HANDOFF_MAGIC));
  wr32(handoff + 8, MOTA_SD_HANDOFF_VERSION);
  wr32(handoff + 12, SD_FIRST_SECTOR);
  wr32(handoff + 16, sectors);
  wr32(handoff + 20, total);
  wr32(handoff + 24, ~total);
  wr32(handoff + 28, SD_CARD_SECTORS);
  wr32(handoff + 32, mota_sd_handoff_crc32(handoff, 32));
  return 1;
}

static int result_ok(bool applied, const uint8_t* expected, uint32_t expected_len) {
  return applied && g_bank0 == BANK_VALID_APP_V && g_crc == 0x1234 &&
         g_size == expected_len && g_settings_writes == 2 &&
         g_app_write_while_valid == 0 && g_gpregret == 0 &&
         g_sd_init_calls == 1 && g_sd_deinit_calls == 1 && g_sd_read_calls > 0 &&
         memcmp(FLASH + MOTA_NRF52_APP_BASE, expected, expected_len) == 0;
}

int main(void) {
  uint8_t* base;
  uint8_t* delta;
  uint8_t* expected;
  long base_len = load("vectors/base.img", &base);
  long delta_len = load("vectors/delta.mota", &delta);
  long expected_len = load("vectors/new.img", &expected);
  int failures = 0;

  printf("[1] SD detools delta: ");
  reset_device(base, (uint32_t)base_len);
  if (!stage_sd_mota(delta, (uint32_t)delta_len)) return 2;
  bool applied = ota_delta_check_and_apply();
  if (result_ok(applied, expected, (uint32_t)expected_len)) {
    printf("PASS\n");
  } else {
    printf("FAIL applied=%d bank=0x%X size=%u settings=%d unsafe=%d\n",
           applied, g_bank0, g_size, g_settings_writes, g_app_write_while_valid);
    failures++;
  }

  printf("[2] SD full image larger than legacy 0x98000 limit: ");
  uint32_t large_len;
  uint8_t* large = make_large_image(&large_len);
  uint32_t full_len;
  uint8_t* full = make_full_mota(large, large_len, &full_len);
  reset_device(base, (uint32_t)base_len);
  if (!stage_sd_mota(full, full_len)) return 2;
  applied = ota_delta_check_and_apply();
  if (large_len > 0x00098000u && result_ok(applied, large, large_len)) {
    printf("PASS (%u-byte image, %u-byte container)\n", large_len, full_len);
  } else {
    printf("FAIL applied=%d bank=0x%X size=%u settings=%d unsafe=%d\n",
           applied, g_bank0, g_size, g_settings_writes, g_app_write_while_valid);
    failures++;
  }

  printf("[3] corrupt SD handoff is non-destructive: ");
  reset_device(base, (uint32_t)base_len);
  if (!stage_sd_mota(delta, (uint32_t)delta_len)) return 2;
  SD_CARD[MOTA_SD_HANDOFF_SECTOR * MOTA_SD_SECTOR_SIZE + 32] ^= 1u;
  applied = ota_delta_check_and_apply();
  if (!applied && g_bank0 == BANK_VALID_APP_V && g_settings_writes == 0 &&
      memcmp(FLASH + MOTA_NRF52_APP_BASE, base, (size_t)base_len) == 0) {
    printf("PASS\n");
  } else {
    printf("FAIL applied=%d bank=0x%X settings=%d\n",
           applied, g_bank0, g_settings_writes);
    failures++;
  }

  free(base);
  free(delta);
  free(expected);
  free(large);
  free(full);
  printf("\n%s (%d failure%s)\n", failures ? "SUITE FAILED" : "SUITE PASSED",
         failures, failures == 1 ? "" : "s");
  return failures ? 1 : 0;
}
