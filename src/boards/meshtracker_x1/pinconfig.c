/* SPDX-License-Identifier: MIT */
#include "boards.h"
#include "uf2/configkeys.h"

__attribute__((used, section(".bootloaderConfig"))) const uint32_t bootloaderConfig[] = {
  /* CF2 START */
  CFG_MAGIC0,
  CFG_MAGIC1,
  5,
  100,
  204,
  0x100000, // FLASH_BYTES
  205,
  0x40000, // RAM_BYTES (upper 64 KiB reserved by the internal-profile linker)
  208,
  (USB_DESC_VID << 16) | USB_DESC_UF2_PID,
  209,
  0xada52840, // UF2_FAMILY
  210,
  0x20, // PINS_PORT_SIZE
  0, 0, 0, 0, 0, 0, 0, 0
  /* CF2 END */
};

// No board_init2/teardown2 overrides: deliberately leave all unverified
// power/flash/peripheral outputs at their reset input state. Common board
// setup configures only the confirmed LEDs and active-high user button.
