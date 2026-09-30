/*
 * The MIT License (MIT)
 *
 * Copyright (c) 2018 Ha Thach for Adafruit Industries
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

#ifndef _MESHTINY_H
#define _MESHTINY_H

// Source-verified port; hardware qualification is pending.
// See docs/seven-board-pin-provenance.md for manufacturer and blame evidence.
#define UICR_REGOUT0_VALUE UICR_REGOUT0_VOUT_3V3

#define LEDS_NUMBER 2
#define LED_PRIMARY_PIN PINNUM(1, 3)
#define LED_SECONDARY_PIN PINNUM(1, 4)
#define LED_STATE_ON 1

// Manufacturer instructions use the side button for USB and the top switch
// held down for BLE. MeshCore and Meshtastic agree on these physical inputs.
#define BUTTON_DFU PINNUM(0, 9)
#define BUTTON_DFU_OTA PINNUM(0, 4)
#define BUTTON_PULL NRF_GPIO_PIN_PULLUP

// Meshtastic's manufacturer-authored port deliberately moves CS, IO0 and IO2
// away from the encoder/buzzer pins of the original GAT-style flash mapping.
#define MOTA_QSPI_SCK_PIN PINNUM(0, 3)
#define MOTA_QSPI_CSN_PIN PINNUM(0, 22)
#define MOTA_QSPI_IO0_PIN PINNUM(0, 27)
#define MOTA_QSPI_IO1_PIN PINNUM(0, 29)
#define MOTA_QSPI_IO2_PIN PINNUM(0, 21)
#define MOTA_QSPI_IO3_PIN PINNUM(0, 2)

#define BLEDIS_MANUFACTURER "MTools Tec"
#define BLEDIS_MODEL "MT001"

// Shared VID/PID with the manufacturer's shipped Meshtiny bootloader.
// Its downloadable UF2 CF2 confirms this identity. DEVICE_NAME remains unique.
#define USB_DESC_VID 0x239A
#define USB_DESC_UF2_PID 0x0029
#define USB_DESC_CDC_ONLY_PID 0x002A

#define UF2_PRODUCT_NAME "Meshtiny Board"
#define UF2_VOLUME_LABEL "MESHTINY"
#define UF2_BOARD_ID "Meshtiny-MT001-Board"
#define UF2_INDEX_URL "https://shop.mtoolstec.com/product/meshtiny"

#endif // _MESHTINY_H
