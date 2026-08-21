#include "bootloader_image.h"

#include <stddef.h>
#include <string.h>

uint32_t bootloader_image_crc32(uint8_t const* image, size_t image_size, size_t crc_offset) {
  uint32_t crc = UINT32_MAX;

  for (size_t i = 0; i < image_size; i++) {
    uint8_t const value = (i >= crc_offset && i < crc_offset + sizeof(uint32_t)) ? 0 : image[i];
    crc ^= value;
    for (uint8_t bit = 0; bit < 8; bit++) {
      crc = (crc >> 1) ^ (0xEDB88320UL & (uint32_t)-(int32_t)(crc & 1U));
    }
  }

  return ~crc;
}

bool bootloader_image_validate(uint8_t const* image, uint32_t image_start, uint32_t image_size,
                               uint32_t expected_board_id, char const* expected_device_name) {
  if (image == NULL || image_size < 8U || expected_device_name == NULL) {
    return false;
  }
  char   expected_name[BOOTLOADER_UPDATE_DEVICE_NAME_SIZE] = {0};
  size_t expected_len = 0;
  while (expected_len < sizeof(expected_name) && expected_device_name[expected_len] != '\0') {
    expected_len++;
  }
  if (expected_len == sizeof(expected_name)) {
    return false;
  }
  memcpy(expected_name, expected_device_name, expected_len);
  uint32_t const initial_sp = (uint32_t)image[0] | ((uint32_t)image[1] << 8) |
                              ((uint32_t)image[2] << 16) | ((uint32_t)image[3] << 24);
  uint32_t const reset = (uint32_t)image[4] | ((uint32_t)image[5] << 8) |
                         ((uint32_t)image[6] << 16) | ((uint32_t)image[7] << 24);
#if defined(NRF52833_XXAA)
  uint32_t const ram_end = 0x20020000UL;
#else
  uint32_t const ram_end = 0x20040000UL;
#endif
  uint32_t const reset_addr = reset & ~1UL;
  if ((initial_sp & 7U) != 0 || initial_sp < 0x20000000UL || initial_sp > ram_end ||
      (reset & 1U) == 0 || reset_addr < image_start ||
      (uint64_t)reset_addr >= (uint64_t)image_start + image_size) {
    return false;
  }

  bool found = false;
  for (size_t offset = 0; offset + sizeof(bootloader_update_manifest_t) <= image_size;
       offset += sizeof(uint32_t)) {
    bootloader_update_manifest_t const* manifest = (void const*)(image + offset);
    if (manifest->magic0 != BOOTLOADER_UPDATE_MANIFEST_MAGIC0 ||
        manifest->magic1 != BOOTLOADER_UPDATE_MANIFEST_MAGIC1) {
      continue;
    }

    if (manifest->version != BOOTLOADER_UPDATE_MANIFEST_VERSION ||
        manifest->header_size != sizeof(bootloader_update_manifest_t) ||
        manifest->image_start != image_start || manifest->image_size != image_size ||
        manifest->board_id != expected_board_id ||
        memcmp(manifest->device_name, expected_name, sizeof(expected_name)) != 0) {
      // Ignore magic words emitted in a literal pool; the real manifest must
      // also have the complete, self-consistent header.
      continue;
    }

    size_t const crc_offset = offset + offsetof(bootloader_update_manifest_t, crc32);
    if (bootloader_image_crc32(image, image_size, crc_offset) != manifest->crc32) {
      continue;
    }
    if (found) {
      return false;
    }
    found = true;
  }

  return found;
}
