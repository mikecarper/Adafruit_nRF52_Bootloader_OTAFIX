#ifndef BOOTLOADER_IMAGE_H_
#define BOOTLOADER_IMAGE_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define BOOTLOADER_UPDATE_MANIFEST_MAGIC0       0x464D4C42UL
#define BOOTLOADER_UPDATE_MANIFEST_MAGIC1       0x31435243UL
#define BOOTLOADER_UPDATE_MANIFEST_VERSION      1U
#define BOOTLOADER_UPDATE_DEVICE_NAME_SIZE      16U

typedef struct {
  uint32_t magic0;
  uint32_t magic1;
  uint16_t version;
  uint16_t header_size;
  uint32_t image_start;
  uint32_t image_size;
  uint32_t board_id;
  char device_name[BOOTLOADER_UPDATE_DEVICE_NAME_SIZE];
  uint32_t crc32;
} bootloader_update_manifest_t;

typedef char bootloader_update_manifest_size_must_be_44
  [(sizeof(bootloader_update_manifest_t) == 44) ? 1 : -1];

uint32_t bootloader_image_crc32(uint8_t const* image, size_t image_size, size_t crc_offset);
bool bootloader_image_validate(uint8_t const* image, uint32_t image_start, uint32_t image_size,
                               uint32_t expected_board_id, char const* expected_device_name);

#endif
