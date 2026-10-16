#pragma once

#include <stdint.h>
#include <stdbool.h>

// Adafruit BLEDfu direct-jumps from the application with this magic. A hardware
// reset is required before DFU so bootloader-installed ACL/BPROT protection no
// longer covers the bootloader settings page.
#define DFU_MAGIC_OTA_APPJUM 0xB1u
#define DFU_MAGIC_OTA_RESET  0xA8u

static inline uint8_t dfu_entry_reset_magic(uint8_t gpregret) {
  return gpregret == DFU_MAGIC_OTA_APPJUM ? DFU_MAGIC_OTA_RESET : gpregret;
}

typedef enum {
  DFU_SINGLE_BUTTON_UNCHANGED,
  DFU_SINGLE_BUTTON_USB,
  DFU_SINGLE_BUTTON_BLE,
  DFU_SINGLE_BUTTON_USB_PROBE,
} dfu_single_button_route_t;

// Opt-in policy for carriers whose one real button requests USB when a host is
// present, but must still offer battery-only BLE recovery. The bounded USB
// probe owns VBUS settling/enumeration; do not sample cold VBUS once here.
static inline dfu_single_button_route_t dfu_entry_single_button_route(
  bool explicit_ble, bool explicit_usb, bool double_reset, bool button_held) {
  if (explicit_ble) return DFU_SINGLE_BUTTON_BLE;
  if (explicit_usb || double_reset) return DFU_SINGLE_BUTTON_USB;
  return button_held ? DFU_SINGLE_BUTTON_USB_PROBE : DFU_SINGLE_BUTTON_UNCHANGED;
}
