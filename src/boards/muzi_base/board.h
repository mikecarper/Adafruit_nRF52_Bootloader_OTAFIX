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

#ifndef _MUZI_BASE_H
#define _MUZI_BASE_H

// Source-verified port; hardware qualification is pending.
// See docs/meshcore-hardware-coverage.md for the pin and identity evidence.
#define UICR_REGOUT0_VALUE UICR_REGOUT0_VOUT_3V3

#define LEDS_NUMBER 2
#define LED_PRIMARY_PIN PINNUM(1, 4)
#define LED_SECONDARY_PIN PINNUM(1, 3)
#define LED_STATE_ON 0

#define BUTTON_DFU PINNUM(0, 10)
#define BUTTON_DFU_OTA PINNUM(0, 10)
#define BUTTON_PULL NRF_GPIO_PIN_PULLUP

// Physical Nordic pin numbers; not Arduino pin indices.
#define MOTA_QSPI_SCK_PIN PINNUM(0, 3)
#define MOTA_QSPI_CSN_PIN PINNUM(0, 26)
#define MOTA_QSPI_IO0_PIN PINNUM(0, 30)
#define MOTA_QSPI_IO1_PIN PINNUM(0, 29)
#define MOTA_QSPI_IO2_PIN PINNUM(0, 28)
#define MOTA_QSPI_IO3_PIN PINNUM(0, 2)

#define BLEDIS_MANUFACTURER "Muzi Works"
#define BLEDIS_MODEL "Muzi Base"

// Shared VID/PID with the manufacturer's shipped bootloader. This retains
// factory UF2 compatibility; the unique DEVICE_NAME binds OTAFIX updates.
#define USB_DESC_VID 0x239A
#define USB_DESC_UF2_PID 0x0081
#define USB_DESC_CDC_ONLY_PID 0x0081

#define UF2_PRODUCT_NAME "Muzi Base"
#define UF2_VOLUME_LABEL "MUZIBBOOT"
#define UF2_BOARD_ID "muzi-Base-Board"
#define UF2_INDEX_URL "https://muzi.works"

#endif // _MUZI_BASE_H
