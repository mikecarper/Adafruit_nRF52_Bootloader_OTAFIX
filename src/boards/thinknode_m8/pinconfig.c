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
  0x100000,                                // FLASH_BYTES
  205,
  0x40000,                                 // RAM_BYTES
  208,
  (USB_DESC_VID << 16) | USB_DESC_UF2_PID, // Invalid draft identity; cannot qualify a bootloader update.
  209,
  0xada52840,                              // UF2_FAMILY
  210,
  0x20,                                    // PINS_PORT_SIZE
  0,
  0,
  0,
  0,
  0,
  0,
  0,
  0
  /* CF2 END */
};

static void peripherals_off(void) {
  const uint32_t pins[] = {M8_DISPLAY_POWER_PIN, M8_FRONTLIGHT_PIN, M8_GPS_POWER_PIN, M8_ADC_POWER_PIN, M8_BUZZER_PIN};
  for (unsigned i = 0; i < sizeof(pins) / sizeof(pins[0]); ++i) {
    // Set the output latch before enabling output, avoiding a high pulse.
    nrf_gpio_pin_clear(pins[i]);
    nrf_gpio_cfg_output(pins[i]);
  }
}

void board_init2(void) {
  // Leave P0.13 untouched: sources disagree on I2C rail vs. power-enable role.
  // Never use PPS P0.14 or the VBUS divider P1.03 as LEDs/USB detection.
  peripherals_off();
}

void board_teardown2(void) {
  peripherals_off();
}
