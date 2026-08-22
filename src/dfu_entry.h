#pragma once

#include <stdint.h>

// Adafruit BLEDfu direct-jumps from the application with this magic. A hardware
// reset is required before DFU so bootloader-installed ACL/BPROT protection no
// longer covers the bootloader settings page.
#define DFU_MAGIC_OTA_APPJUM 0xB1u
#define DFU_MAGIC_OTA_RESET  0xA8u

static inline uint8_t dfu_entry_reset_magic(uint8_t gpregret) {
  return gpregret == DFU_MAGIC_OTA_APPJUM ? DFU_MAGIC_OTA_RESET : gpregret;
}
