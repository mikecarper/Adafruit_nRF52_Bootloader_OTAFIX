// Exercise the production GhostFAT reader and writer with T-Echo Lite's
// identity/layout. Only hardware flash accesses are redirected to a host array.
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static uint8_t flash_image[1024u * 1024u];
static unsigned erases, programs, invalidations;

static const void *flash_pointer(const void *ptr, size_t len) {
  uintptr_t address = (uintptr_t)ptr;
  if (address < sizeof(flash_image)) {
    assert(len <= sizeof(flash_image) - address);
    return flash_image + address;
  }
  return ptr;
}

static void *flash_memcpy(void *dst, const void *src, size_t len) {
  return memcpy(dst, flash_pointer(src, len), len);
}

static int flash_memcmp(const void *left, const void *right, size_t len) {
  return memcmp(flash_pointer(left, len), flash_pointer(right, len), len);
}

#define memcpy flash_memcpy
#define memcmp flash_memcmp
#include "../src/usb/uf2/ghostfat.c"
#undef memcpy
#undef memcmp

uf2_test_ficr_t uf2_test_ficr = {.INFO = {.RAM = 256}};

void flash_nrf5x_erase(uint32_t dst, uint32_t len) {
  assert(len == CODE_PAGE_SIZE);
  dst &= ~(CODE_PAGE_SIZE - 1u);
  assert(dst >= DFU_BANK_0_REGION_START && dst + len <= USER_FLASH_END);
  memset(flash_image + dst, 0xFF, len);
  erases++;
}
void flash_nrf5x_discard(void) {}
void flash_nrf5x_invalidate_app_settings(void) { invalidations++; }
void flash_nrf5x_write_erased(uint32_t dst, const void *src, uint32_t len) {
  assert(dst >= DFU_BANK_0_REGION_START && dst + len <= USER_FLASH_END);
  memcpy(flash_image + dst, src, len);
  programs++;
}
void flash_nrf5x_write(uint32_t dst, const void *src, uint32_t len, bool need_erase) {
  (void)dst; (void)src; (void)len; (void)need_erase;
  assert(!"unexpected bootloader write");
}
void flash_nrf5x_flush(bool need_erase) { (void)need_erase; }
bool bootloader_app_is_valid(void) { return true; }
bool ota_delta_live_app_fits_below(uint32_t ceiling) { (void)ceiling; return true; }
uint32_t dfu_image_policy_validate(const uint8_t *image, uint32_t size,
                                   const dfu_start_packet_t *packet) {
  (void)image; (void)size; (void)packet;
  assert(!"unexpected bootloader validation");
  return 1;
}

static uint16_t le16(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }
static uint32_t le32(const uint8_t *p) {
  return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static void test_volume(void) {
  uint8_t sector[512] __attribute__((aligned(4)));
  uint8_t copy[512] __attribute__((aligned(4)));
  read_block(0, sector);
  assert(sector[510] == 0x55 && sector[511] == 0xAA);
  assert(le16(sector + 11) == 512 && sector[13] == 1 && sector[16] == 2);
  uint32_t reserved = le16(sector + 14);
  uint32_t fat_sectors = le16(sector + 22);
  uint32_t root = reserved + 2u * fat_sectors;
  uint32_t first_data = root + (le16(sector + 17) * 32u + 511u) / 512u;
  read_block(root, sector);
  assert(memcmp(sector, "TECHOLITE  ", 11) == 0 && sector[11] == 0x28);
  assert(memcmp(sector + 32, "INFO_UF2TXT", 11) == 0);
  assert(memcmp(sector + 64, "INDEX   HTM", 11) == 0);
  for (unsigned entry = 1; entry <= 2; entry++) {
    assert(le16(sector + 32u * entry + 26) == 0);
    assert(le32(sector + 32u * entry + 28) == 0);
  }
  assert(memcmp(sector + 96, "CURRENT UF2", 11) == 0);
  assert(le16(sector + 96 + 26) == 2 && sector[128] == 0);
  uint32_t blocks = le32(sector + 96 + 28) / 512u;
  assert(blocks == (USER_FLASH_END - USER_FLASH_START) / 256u);
  assert(first_data == CURRENT_UF2_FIRST_LBA);

  // Both FATs must agree, with one complete file chain and free space after it.
  for (uint32_t s = 0; s < fat_sectors; s++) {
    read_block(reserved + s, sector);
    read_block(reserved + fat_sectors + s, copy);
    assert(memcmp(sector, copy, sizeof(sector)) == 0);
    for (uint32_t i = 0; i < 256u; i++) {
      uint32_t cluster = s * 256u + i;
      uint16_t expected = cluster == 0 ? 0xFFF8u : cluster == 1 ? 0xFFFFu : 0u;
      if (cluster >= 2 && cluster < blocks + 2) {
        expected = cluster == blocks + 1 ? 0xFFFFu : (uint16_t)(cluster + 1);
      }
      assert(le16(sector + 2u * i) == expected);
    }
  }

  WriteState state = {0};
  WriteState untouched = state;
  for (uint32_t i = 0; i < blocks; i++) {
    read_block(first_data + i, sector);
    UF2_Block *block = (void *)sector;
    assert(is_uf2_block(block));
    assert(block->familyID == CFG_UF2_BOARD_APP_ID);
    assert(block->blockNo == i && block->numBlocks == blocks);
    assert(block->targetAddr == USER_FLASH_START + 256u * i);
    assert(memcmp(block->data, flash_image + block->targetAddr, 256) == 0);
    // Cached writes to CURRENT's physical extent must not start an update.
    assert(write_block(first_data + i, sector, &state) == 512);
    assert(memcmp(&state, &untouched, sizeof(state)) == 0);
  }
  assert(erases == 0 && programs == 0 && invalidations == 0);

  // A new file in free clusters must still flash, even though CURRENT is visible.
  UF2_Block app = {
    .magicStart0 = UF2_MAGIC_START0, .magicStart1 = UF2_MAGIC_START1,
    .magicEnd = UF2_MAGIC_END, .flags = UF2_FLAG_FAMILYID,
    .targetAddr = DFU_BANK_0_REGION_START, .payloadSize = 256,
    .numBlocks = 1, .familyID = CFG_UF2_BOARD_APP_ID
  };
  uint32_t vectors[] = {0x20040000u, DFU_BANK_0_REGION_START + 9u};
  memcpy(app.data, vectors, sizeof(vectors));
  uint32_t free_lba = first_data + blocks;
  assert(write_block(free_lba, (uint8_t *)&app, &state) == 0);
  assert(write_block(free_lba, (uint8_t *)&app, &state) == 0);
  assert(write_block(free_lba, (uint8_t *)&app, &state) == 512);
  assert(state.appValidated && !state.aborted && state.numWritten == 1);
  assert(erases == 1 && programs == 1 && invalidations == 1);
  assert(memcmp(flash_image + app.targetAddr, app.data, 256) == 0);
}

int main(void) {
  for (size_t i = 0; i < sizeof(flash_image); i++) flash_image[i] = (uint8_t)(i ^ (i >> 8));
  test_volume();
  puts("T-Echo Lite UF2: empty INFO/INDEX, FAT, readback, cached-write guard and drag-and-drop PASS");
  return 0;
}
