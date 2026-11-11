#include "dfu_image_policy.h"

#include <stdbool.h>
#include <stddef.h>

#include "board.h"
#include "nrf_error.h"
#include "nrf_sdm.h"
#include "usb/uf2/bootloader_image.h"

#ifndef USB_DESC_VID
  #error "USB_DESC_VID is required to identify manual bootloader images"
#endif
#ifndef USB_DESC_UF2_PID
  #error "USB_DESC_UF2_PID is required to identify manual bootloader images"
#endif
#ifndef MOTA_SOFTDEVICE_FAMILY
  #error "MOTA_SOFTDEVICE_FAMILY is required"
#endif

typedef struct {
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

  uint32_t const family = read_le32(image + SD_ID_OFFSET);
  info->fwid     = read_le16(image + SD_FWID_OFFSET);
  info->app_base = read_le32(image + SD_SIZE_OFFSET);

  if (family != MOTA_SOFTDEVICE_FAMILY || info->fwid == 0U ||
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
  uint32_t const expected_board = ((uint32_t)USB_DESC_VID << 16) | USB_DESC_UF2_PID;
  bootloader_image_info_t candidate;
  if (!bootloader_image_manual_compatible(image, BOOTLOADER_REGION_START,
                                          image_size, expected_board, &candidate)) {
    return false;
  }

  // Older/manual images need no project-specific envelope or full-region
  // padding. When compatibility metadata is supplied, keep its SD/layout
  // assertions authoritative rather than silently ignoring a known mismatch.
  if (candidate.softdevice_family != 0U) {
    uint16_t const expected_fwid = incoming_sd ? incoming_sd->fwid :
                                               dfu_policy_runtime_softdevice_fwid();
    uint32_t const expected_app_base = incoming_sd ? incoming_sd->app_base :
                                                    dfu_policy_runtime_app_base();
    return candidate.softdevice_family == MOTA_SOFTDEVICE_FAMILY &&
           candidate.softdevice_fwid == expected_fwid &&
           candidate.app_base == expected_app_base &&
           candidate.layout_abi == BOOTLOADER_UPDATE_LAYOUT_ABI;
  }

  return true;
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
    // their matching bootloader selected by the operator.
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
