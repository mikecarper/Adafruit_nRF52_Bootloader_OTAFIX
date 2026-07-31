#include "bootloader_image.h"

#include "boards.h"
#include "dfu_types.h"

#ifndef DEVICE_NAME
  #error "DEVICE_NAME is required for a bootloader update manifest"
#endif

__attribute__((used, section(".bootloaderManifest"))) const bootloader_update_manifest_t
  bootloaderUpdateManifest = {
    .magic0 = BOOTLOADER_UPDATE_MANIFEST_MAGIC0,
    .magic1 = BOOTLOADER_UPDATE_MANIFEST_MAGIC1,
    .version = BOOTLOADER_UPDATE_MANIFEST_VERSION,
    .header_size = sizeof(bootloader_update_manifest_t),
    .image_start = BOOTLOADER_REGION_START,
    .image_size = DFU_BL_IMAGE_MAX_SIZE,
    .board_id = ((uint32_t)USB_DESC_VID << 16) | USB_DESC_UF2_PID,
    .device_name = DEVICE_NAME,
    .crc32 = 0,
  };
