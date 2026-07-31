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
        manifest->device_name[BOOTLOADER_UPDATE_DEVICE_NAME_SIZE - 1] != '\0' ||
        strncmp(manifest->device_name, expected_device_name,
                BOOTLOADER_UPDATE_DEVICE_NAME_SIZE) != 0) {
      // Ignore magic words emitted in a literal pool; the real manifest must
      // also have the complete, self-consistent header.
      continue;
    }

    size_t const crc_offset = offset + offsetof(bootloader_update_manifest_t, crc32);
    return bootloader_image_crc32(image, image_size, crc_offset) == manifest->crc32;
  }

  return false;
}
