/* SPDX-License-Identifier: MIT */

#ifndef _HELTEC_MESH_SOLAR_H
#define _HELTEC_MESH_SOLAR_H

// Internal-staging qualification port: do not infer LED/flash wiring from
// Heltec's contradictory BSP. See docs/meshsolar-qualification.md.
#if !defined(OTAFIX_SOLAR_QUALIFICATION_ONLY) || OTAFIX_SOLAR_QUALIFICATION_ONLY != 1
  #error "Mesh Solar requires an explicit qualification build"
#endif

// No status LEDs or NeoPixel outputs. In particular P1.03 is battery shutdown,
// not an LED; P0.12/P1.15 indicator type differs among published sources.
#define LEDS_NUMBER 0
#define LED_STATE_ON 0

// Manufacturer carrier pin map and both firmware variants agree on this key.
#define BUTTON_DFU PINNUM(1, 10)
#define BUTTON_DFU_OTA PINNUM(1, 10)
#define BUTTON_PULL NRF_GPIO_PIN_PULLUP

// Heltec's author-confirmed watchdog revision (Meshtastic PR 9337) uses
// previously-unused P0.09 DONE/P0.10 WAKE. Keep WAKE at its reset input state.
// The common bootloader code feeds on entry, during DFU and before flash apply.
#define EXTERNAL_WATCHDOG_DONE_PIN PINNUM(0, 9)
#define EXTERNAL_WATCHDOG_FEED_INTERVAL_MS (60UL * 1000UL)
#define EXTERNAL_WATCHDOG_FEED_PULSE_MS 1UL

#define BLEDIS_MANUFACTURER "Heltec Automation"
#define BLEDIS_MODEL "Mesh Solar INT QUAL"

// Preserve the verified legacy HT-n5262 factory CF2 identity. This shared
// manufacturer identity is not an allocation template for new third parties.
// The unique SOLARINT_DFU mOTA identity prevents a cross-Heltec self-update.
#define USB_DESC_VID 0x239A
#define USB_DESC_UF2_PID 0x0071
#define USB_DESC_CDC_ONLY_PID 0x0071

#define UF2_PRODUCT_NAME "Heltec Mesh Solar INT QUAL"
#define UF2_VOLUME_LABEL "SOLARQUAL"
#define UF2_BOARD_ID "HT-n5262"
#define UF2_INDEX_URL "https://heltec.org/project/meshsolar/"

#endif // _HELTEC_MESH_SOLAR_H
