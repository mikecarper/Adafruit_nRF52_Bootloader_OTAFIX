#include "bootloader_image.h"

#include "boards.h"
#include "dfu_types.h"

#ifndef DEVICE_NAME
  #error "DEVICE_NAME is required for a bootloader update manifest"
#endif
#ifndef MOTA_BOOTLOADER_VERSION
  #error "MOTA_BOOTLOADER_VERSION must be derived from the canonical OTAFIX release tag"
#endif
#ifndef MOTA_SOFTDEVICE_FAMILY
  #error "MOTA_SOFTDEVICE_FAMILY is required"
#endif
#ifndef MOTA_SOFTDEVICE_FWID
  #error "MOTA_SOFTDEVICE_FWID is required"
#endif
#ifndef MOTA_APP_BASE
  #error "MOTA_APP_BASE is required"
#endif
#if MOTA_BOOTLOADER_VERSION == 0 || MOTA_BOOTLOADER_VERSION == 0xFFFFFFFFu || \
  (MOTA_BOOTLOADER_VERSION & 0xFFu) == 0
  #error "MOTA_BOOTLOADER_VERSION must have a valid nonzero release channel"
#endif

__attribute__((used, section(".bootloaderManifest"))) const bootloader_update_envelope_t
  bootloaderUpdateManifest = {
    .manifest = {
      .magic0 = BOOTLOADER_UPDATE_MANIFEST_MAGIC0,
      .magic1 = BOOTLOADER_UPDATE_MANIFEST_MAGIC1,
      .version = BOOTLOADER_UPDATE_MANIFEST_VERSION,
      .header_size = sizeof(bootloader_update_manifest_t),
      .image_start = BOOTLOADER_REGION_START,
      .image_size = DFU_BL_IMAGE_MAX_SIZE,
      .board_id = ((uint32_t)USB_DESC_VID << 16) | USB_DESC_UF2_PID,
      .device_name = DEVICE_NAME,
      .crc32 = 0,
    },
    .extension = {
      .magic0 = BOOTLOADER_UPDATE_EXTENSION_MAGIC0,
      .magic1 = BOOTLOADER_UPDATE_EXTENSION_MAGIC1,
      .version = BOOTLOADER_UPDATE_EXTENSION_VERSION,
      .header_size = sizeof(bootloader_update_extension_t),
      .boot_version = MOTA_BOOTLOADER_VERSION,
      .softdevice_family = MOTA_SOFTDEVICE_FAMILY,
      .softdevice_fwid = MOTA_SOFTDEVICE_FWID,
      .app_base = MOTA_APP_BASE,
      .layout_abi = BOOTLOADER_UPDATE_LAYOUT_ABI,
      .compat_flags = 0,
      .reserved = 0,
    },
  };
