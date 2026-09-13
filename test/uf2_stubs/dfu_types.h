#pragma once
#include <stdint.h>
#define MBR_SIZE 0x1000u
#define CODE_PAGE_SIZE 0x1000u
#define BOOTLOADER_REGION_START 0xF4000u
#define BOOTLOADER_MBR_PARAMS_PAGE_ADDRESS 0xFE000u
#define DFU_APP_DATA_RESERVED 0xA000u
#define DFU_BL_IMAGE_MAX_SIZE 0xA000u
#define DFU_BANK_0_REGION_START 0x26000u
#define DFU_UPDATE_BL 2u
#define NRF_SUCCESS 0u
typedef struct {
  uint32_t dfu_update_mode;
  uint32_t sd_image_size;
  uint32_t bl_image_size;
  uint32_t app_image_size;
} dfu_start_packet_t;
