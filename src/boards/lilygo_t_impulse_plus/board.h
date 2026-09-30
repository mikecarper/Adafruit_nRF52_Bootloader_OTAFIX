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

#ifndef _LILYGO_T_IMPULSE_PLUS_H
#define _LILYGO_T_IMPULSE_PLUS_H

// Source-verified port; hardware qualification is pending.
// See docs/meshcore-hardware-coverage.md for the pin and identity evidence.
#define UICR_REGOUT0_VALUE UICR_REGOUT0_VOUT_3V3

#define LEDS_NUMBER 1
#define LED_PRIMARY_PIN PINNUM(0, 17)
#define LED_STATE_ON 0

#define BUTTON_DFU PINNUM(0, 24)
#define BUTTON_DFU_OTA PINNUM(0, 24)
#define BUTTON_PULL NRF_GPIO_PIN_PULLUP

// Physical Nordic pin numbers; not Arduino pin indices.
#define MOTA_QSPI_SCK_PIN PINNUM(0, 4)
#define MOTA_QSPI_CSN_PIN PINNUM(0, 12)
#define MOTA_QSPI_IO0_PIN PINNUM(0, 6)
#define MOTA_QSPI_IO1_PIN PINNUM(1, 9)
#define MOTA_QSPI_IO2_PIN PINNUM(0, 8)
#define MOTA_QSPI_IO3_PIN PINNUM(0, 26)
#define MOTA_QSPI_POWER_PIN PINNUM(0, 14)
#define MOTA_QSPI_POWER_ACTIVE 1

#define BLEDIS_MANUFACTURER "LilyGo"
#define BLEDIS_MODEL "T-Impulse Plus"

// Shared VID/PID with the manufacturer's shipped bootloader. This retains
// factory UF2 compatibility; the unique DEVICE_NAME binds OTAFIX updates.
#define USB_DESC_VID 0x239A
#define USB_DESC_UF2_PID 0x00DA
#define USB_DESC_CDC_ONLY_PID 0x00DA

#define UF2_PRODUCT_NAME "T-Impulse Plus"
#define UF2_VOLUME_LABEL "TIMPBOOT"
#define UF2_BOARD_ID "LilyGo-T-Impulse-Plus"
#define UF2_INDEX_URL "https://github.com/Xinyuan-LilyGO/T-Impulse-Plus"

#endif // _LILYGO_T_IMPULSE_PLUS_H
