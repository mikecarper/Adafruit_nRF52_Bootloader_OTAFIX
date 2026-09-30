/* SPDX-License-Identifier: MIT */

#ifndef _THINKNODE_M8_H
#define _THINKNODE_M8_H

// V0.3 source port, pending factory identity and physical qualification.
// See docs/seven-board-pin-provenance.md. Never substitute the M1 profile:
// its button is this board's display enable and its LED is GNSS PPS.
#if !defined(OTAFIX_M8_COMPILE_ONLY) || OTAFIX_M8_COMPILE_ONLY != 1
  #error "ThinkNode M8 is compile-only until its factory USB identity is verified"
#endif

#define LEDS_NUMBER  0
#define LED_STATE_ON 1

// Separate active-low button. The encoder press is active high on P0.06;
// it must not share this pull-up/active-low bootloader button definition.
#define BUTTON_DFU     PINNUM(0, 12)
#define BUTTON_DFU_OTA PINNUM(0, 12)
#define BUTTON_PULL    NRF_GPIO_PIN_PULLUP

// Onboard 2 MiB MX25R1635F, physical Nordic numbering (not Arduino indices).
#define MOTA_QSPI_SCK_PIN    PINNUM(1, 14)
#define MOTA_QSPI_CSN_PIN    PINNUM(1, 15)
#define MOTA_QSPI_IO0_PIN    PINNUM(1, 12)
#define MOTA_QSPI_IO1_PIN    PINNUM(1, 13)
#define MOTA_QSPI_IO2_PIN    PINNUM(0, 7)
#define MOTA_QSPI_IO3_PIN    PINNUM(0, 5)

#define M8_DISPLAY_POWER_PIN PINNUM(1, 10)
#define M8_FRONTLIGHT_PIN    PINNUM(1, 11)
#define M8_GPS_POWER_PIN     PINNUM(0, 16)
#define M8_ADC_POWER_PIN     PINNUM(1, 8)
#define M8_BUZZER_PIN        PINNUM(1, 1)

#define BLEDIS_MANUFACTURER  "ELECROW"
#define BLEDIS_MODEL         "ThinkNodeM8 DRAFT"

// Invalid, compile-only fixtures, NOT assigned USB identifiers. The actual
// factory VID/PID and UF2 board string have not been established. Zero CF2/
// BLMF identity cannot match a qualified target; manual recovery rejects it too.
// Do not copy M1's Adafruit identity or the generic application board HWIDs.
#define USB_DESC_VID          0x0000
#define USB_DESC_UF2_PID      0x0000
#define USB_DESC_CDC_ONLY_PID 0x0000
// uf2cfg.h omits the derived application ID when the USB fixtures are zero.
// Keep that ID invalid too, solely to compile the existing UF2 code paths.
#define CFG_UF2_BOARD_APP_ID 0x00000000

#define UF2_PRODUCT_NAME     "ThinkNode M8 DRAFT - DO NOT FLASH"
#define UF2_VOLUME_LABEL     "M8DRAFT"
#define UF2_BOARD_ID         "nRF52840-ThinkNodeM8-DRAFT"
#define UF2_INDEX_URL        "https://www.elecrow.com"

#endif // _THINKNODE_M8_H
