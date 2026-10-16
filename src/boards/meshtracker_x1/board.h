/* SPDX-License-Identifier: MIT */

#ifndef _MESHTRACKER_X1_H
#define _MESHTRACKER_X1_H

// Internal-staging qualification candidate, not a Wio Tracker L1 alias.
// Pin and factory-identity evidence: docs/meshtracker-x1-qualification.md.
// No external flash, sensor, GNSS, RTC, haptic, or power-latch pins are driven.
#if !defined(OTAFIX_X1_QUALIFICATION_ONLY) || OTAFIX_X1_QUALIFICATION_ONLY != 1
  #error "MeshTracker X1 requires an explicit qualification build"
#endif

#define LEDS_NUMBER 2
#define LED_PRIMARY_PIN PINNUM(0, 3)
#define LED_SECONDARY_PIN PINNUM(0, 24)
#define LED_STATE_ON 1

// Real X1 button, active HIGH. The common button handler supports pulldown.
// Use the confirmed sole control, not L1's P0.08. Its board-only policy probes
// USB first while held, then falls back to BLE if no host/VBUS arrives.
#define BUTTON_DFU PINNUM(0, 6)
#define BUTTON_DFU_OTA PINNUM(0, 6)
#define BUTTON_PULL NRF_GPIO_PIN_PULLDOWN
#define BUTTON_DFU_PROBE_USB 1

#define BLEDIS_MANUFACTURER "Seeed"
#define BLEDIS_MODEL "MeshTracker X1 QUAL"

// Verified in the manufacturer Bootloader.zip's CF2. Preserve the existing
// factory identity for CDC too; do not copy generic Arduino application HWIDs.
#define USB_DESC_VID 0x2886
#define USB_DESC_UF2_PID 0x0057
#define USB_DESC_CDC_ONLY_PID 0x0057

// Factory board string is preserved. The new DFU name binds this internal
// candidate's mOTA identity separately from future external-staging profiles.
#define UF2_PRODUCT_NAME "Seeed MeshTracker-X1 QUAL"
#define UF2_VOLUME_LABEL "X1QUAL"
#define UF2_BOARD_ID "nRF52840-MeshTracker-X1-v1"
#define UF2_INDEX_URL "https://wiki.seeedstudio.com/sensecap_meshtracker_x1_meshcore/"

#endif // _MESHTRACKER_X1_H
