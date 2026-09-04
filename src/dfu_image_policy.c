#include "dfu_image_policy.h"

#include <stdbool.h>
#include <stddef.h>
#include <string.h>

#include "board.h"
#include "nrf_error.h"
#include "nrf_sdm.h"
#include "usb/uf2/bootloader_image.h"

#ifndef DEVICE_NAME
  #error "DEVICE_NAME is required to bind privileged Legacy DFU images"
#endif
#ifndef USB_DESC_VID
  #error "USB_DESC_VID is required to bind privileged Legacy DFU images"
#endif
#ifndef USB_DESC_UF2_PID
  #error "USB_DESC_UF2_PID is required to bind privileged Legacy DFU images"
#endif
#ifndef MOTA_SOFTDEVICE_FAMILY
  #error "MOTA_SOFTDEVICE_FAMILY is required"
#endif

typedef char dfu_policy_device_name_must_fit
  [(sizeof(DEVICE_NAME) <= BOOTLOADER_UPDATE_DEVICE_NAME_SIZE) ? 1 : -1];

typedef struct {
  uint32_t family;
  uint16_t fwid;
  uint32_t app_base;
} softdevice_image_info_t;

static uint32_t read_le32(uint8_t const* data) {
  return (uint32_t)data[0] | ((uint32_t)data[1] << 8) |
         ((uint32_t)data[2] << 16) | ((uint32_t)data[3] << 24);
}

static uint16_t read_le16(uint8_t const* data) {
  return (uint16_t)data[0] | ((uint16_t)data[1] << 8);
}

uint32_t dfu_start_packet_validate(dfu_start_packet_t const* start_packet,
                                   uint32_t* image_size_out) {
  uint8_t const populated_mode =
    (start_packet->sd_image_size ? DFU_UPDATE_SD : 0U) |
    (start_packet->bl_image_size ? DFU_UPDATE_BL : 0U) |
    (start_packet->app_image_size ? DFU_UPDATE_APP : 0U);
  if (populated_mode == 0U || populated_mode > DFU_UPDATE_APP ||
      start_packet->dfu_update_mode != populated_mode ||
      ((start_packet->sd_image_size | start_packet->bl_image_size |
        start_packet->app_image_size) &
       (sizeof(uint32_t) - 1U)) != 0U) {
    return NRF_ERROR_NOT_SUPPORTED;
  }

  uint32_t image_size;
  if (start_packet->bl_image_size > DFU_BL_IMAGE_MAX_SIZE ||
      __builtin_add_overflow(start_packet->sd_image_size,
                             start_packet->bl_image_size, &image_size) ||
      __builtin_add_overflow(image_size, start_packet->app_image_size,
                             &image_size)) {
    return NRF_ERROR_DATA_SIZE;
  }

  *image_size_out = image_size;
  return NRF_SUCCESS;
}

#ifdef DFU_IMAGE_POLICY_HOST_TEST
extern uint32_t dfu_policy_runtime_app_base(void);
extern uint16_t dfu_policy_runtime_softdevice_fwid(void);
#else
static uint32_t dfu_policy_runtime_app_base(void) {
  return CODE_REGION_1_START;
}

static uint16_t dfu_policy_runtime_softdevice_fwid(void) {
  return is_sd_existed() ? SD_FWID_GET(MBR_SIZE) : 0U;
}
#endif

static bool softdevice_info(uint8_t const* image, uint32_t image_size,
                            softdevice_image_info_t* info) {
  uint32_t const required_size = SD_UNIQUE_STR_OFFSET + SD_UNIQUE_STR_SIZE;
  if (image_size < required_size ||
      image[SD_INFO_STRUCT_SIZE_OFFSET] <=
        (SD_ID_OFFSET - SOFTDEVICE_INFO_STRUCT_OFFSET) ||
      read_le32(image + SOFTDEVICE_INFO_STRUCT_OFFSET + sizeof(uint32_t)) !=
        SD_MAGIC_NUMBER) {
    return false;
  }

  info->family   = read_le32(image + SD_ID_OFFSET);
  info->fwid     = read_le16(image + SD_FWID_OFFSET);
  info->app_base = read_le32(image + SD_SIZE_OFFSET);

  if (info->family != MOTA_SOFTDEVICE_FAMILY || info->fwid == 0U ||
      info->fwid == UINT16_MAX || info->app_base <= MBR_SIZE ||
      info->app_base >= BOOTLOADER_REGION_START ||
      (info->app_base & (CODE_PAGE_SIZE - 1U)) != 0U ||
      image_size > info->app_base - MBR_SIZE) {
    return false;
  }

  return bootloader_image_vectors_valid(image, image_size, MBR_SIZE, image_size);
}

static bool bootloader_info(uint8_t const* image, uint32_t image_size,
                            softdevice_image_info_t const* incoming_sd) {
#ifdef DFU_IMAGE_POLICY_HOST_TEST
  static char const expected_name[BOOTLOADER_UPDATE_DEVICE_NAME_SIZE] = DEVICE_NAME;
#else
  extern const bootloader_update_envelope_t bootloaderUpdateManifest;
  char const* expected_name = bootloaderUpdateManifest.manifest.device_name;
#endif
  uint32_t const expected_board = ((uint32_t)USB_DESC_VID << 16) | USB_DESC_UF2_PID;

  if (image_size != DFU_BL_IMAGE_MAX_SIZE) {
    return false;
  }

  bootloader_image_info_t candidate;
  bootloader_image_format_t const format = bootloader_image_classify(
    image, BOOTLOADER_REGION_START, image_size, expected_board, expected_name,
    &candidate);
  if (format == BOOTLOADER_IMAGE_INVALID) {
    return false;
  }
  if (format == BOOTLOADER_IMAGE_V2) {
    uint16_t const expected_fwid = incoming_sd ? incoming_sd->fwid :
                                               dfu_policy_runtime_softdevice_fwid();
    uint32_t const expected_app_base = incoming_sd ? incoming_sd->app_base :
                                                    dfu_policy_runtime_app_base();
    return candidate.softdevice_family == MOTA_SOFTDEVICE_FAMILY &&
           candidate.softdevice_fwid == expected_fwid &&
           candidate.app_base == expected_app_base &&
           candidate.layout_abi == BOOTLOADER_UPDATE_LAYOUT_ABI;
  }

  // Relocated BLMF-only preview images predate machine-readable layout metadata. They
  // remain useful for deliberate rollback only when an accompanying SD is
  // exactly the runtime layout they were built around. A BL-only update does
  // not alter that already-working layout.
  return incoming_sd == NULL ||
         (incoming_sd->fwid == dfu_policy_runtime_softdevice_fwid() &&
          incoming_sd->app_base == dfu_policy_runtime_app_base());
}

uint32_t dfu_image_policy_validate(uint8_t const* image, uint32_t image_len,
                                   dfu_start_packet_t const* start_packet) {
  if (image == NULL || start_packet == NULL) {
    return NRF_ERROR_NULL;
  }

  uint32_t declared_size;
  if (dfu_start_packet_validate(start_packet, &declared_size) != NRF_SUCCESS ||
      image_len != declared_size) {
    return NRF_ERROR_INVALID_DATA;
  }

  uint8_t const populated_mode = start_packet->dfu_update_mode;

  if (populated_mode == DFU_UPDATE_APP) {
    uint32_t const app_base = dfu_policy_runtime_app_base();
    return bootloader_image_vectors_valid(image, image_len, app_base, image_len) ?
             NRF_SUCCESS : NRF_ERROR_INVALID_DATA;
  }

  softdevice_image_info_t incoming_sd;
  softdevice_image_info_t const* incoming_sd_ptr = NULL;
  if ((populated_mode & DFU_UPDATE_SD) != 0U) {
    if (!softdevice_info(image, start_packet->sd_image_size, &incoming_sd)) {
      return NRF_ERROR_INVALID_DATA;
    }
    incoming_sd_ptr = &incoming_sd;

    // An SD-only replacement must be an exact reinstall.  Sharing a family
    // and application boundary does not prove that the running bootloader's
    // SVC ABI matches a different SoftDevice FWID.  Migrations travel with
    // their matching, board-bound bootloader.
    if ((populated_mode == DFU_UPDATE_SD) &&
        (incoming_sd.fwid != dfu_policy_runtime_softdevice_fwid() ||
         incoming_sd.app_base != dfu_policy_runtime_app_base())) {
      return NRF_ERROR_INVALID_DATA;
    }
  }

  if ((populated_mode & DFU_UPDATE_BL) != 0U &&
      !bootloader_info(image + start_packet->sd_image_size,
                       start_packet->bl_image_size, incoming_sd_ptr)) {
    return NRF_ERROR_INVALID_DATA;
  }

  return NRF_SUCCESS;
}
