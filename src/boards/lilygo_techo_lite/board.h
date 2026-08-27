/*
 * The MIT License (MIT)
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 */

#ifndef _LILYGO_TECHO_LITE_H
#define _LILYGO_TECHO_LITE_H

#define _PINNUM(port, pin) ((port)*32 + (pin))

#define UICR_REGOUT0_VALUE UICR_REGOUT0_VOUT_3V3

#define PIN_LDO_ENABLE _PINNUM(0, 30)

/*------------------------------------------------------------------*/
/* LED
 *------------------------------------------------------------------*/
#define LEDS_NUMBER       2
#define LED_PRIMARY_PIN   _PINNUM(1, 7) // Green
#define LED_SECONDARY_PIN _PINNUM(1, 5) // Blue
#define LED_STATE_ON      0

/*------------------------------------------------------------------*/
/* BUTTON
 *------------------------------------------------------------------*/
#define BUTTON_DFU     _PINNUM(0, 24) // user button
#define BUTTON_DFU_OTA _PINNUM(0, 24) // hold on boot to enter OTA DFU mode
#define BUTTON_PULL    NRF_GPIO_PIN_PULLUP

// On-board 4 MiB QSPI flash used as the raw MeshCore OTA store. The flash and
// its bus are powered by the active-high RT9080 rail.
#define MOTA_QSPI_SCK_PIN      _PINNUM(0, 4)
#define MOTA_QSPI_CSN_PIN      _PINNUM(0, 12)
#define MOTA_QSPI_IO0_PIN      _PINNUM(0, 6)
#define MOTA_QSPI_IO1_PIN      _PINNUM(0, 8)
#define MOTA_QSPI_IO2_PIN      _PINNUM(1, 9)
#define MOTA_QSPI_IO3_PIN      _PINNUM(0, 26)
#define MOTA_QSPI_POWER_PIN    PIN_LDO_ENABLE
#define MOTA_QSPI_POWER_ACTIVE 1

//--------------------------------------------------------------------+
// BLE OTA
//--------------------------------------------------------------------+
#define BLEDIS_MANUFACTURER "LilyGo"
#define BLEDIS_MODEL        "T-Echo-Lite"

//--------------------------------------------------------------------+
// USB
//--------------------------------------------------------------------+
// Legacy compatibility identity inherited from the contributed target. This
// Adafruit VID/PID is not a template for new third-party assignments.
#define USB_DESC_VID          0x239A
#define USB_DESC_UF2_PID      0x00DA
#define USB_DESC_CDC_ONLY_PID 0x00DA

#define UF2_PRODUCT_NAME "LilyGo T-Echo Lite"
#define UF2_VOLUME_LABEL "TECHOLITE"
#define UF2_BOARD_ID     "T-Echo-Lite-nRF52840"
#define UF2_INDEX_URL    "https://lilygo.cc/products/t-echo-lite"

#endif // _LILYGO_TECHO_LITE_H
