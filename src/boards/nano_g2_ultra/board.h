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

#ifndef _NANO_G2_ULTRA_H
#define _NANO_G2_ULTRA_H

// Source-verified port; hardware qualification is pending.
// See docs/seven-board-pin-provenance.md for schematic, factory HEX and blame.
#define LEDS_NUMBER 0
#define LED_STATE_ON 0

// The schematic's SW1 net reaches P1.06 and has a 10k pull-up.
// There is one user button plus a separate hardware reset switch.
#define BUTTON_DFU PINNUM(1, 6)
#define BUTTON_DFU_OTA PINNUM(1, 6)
#define BUTTON_PULL NRF_GPIO_PIN_PULLUP

// Physical Nordic pin numbers; the schematic labels these Flash_SPI_*.
#define MOTA_QSPI_SCK_PIN PINNUM(0, 8)
#define MOTA_QSPI_CSN_PIN PINNUM(1, 7)
#define MOTA_QSPI_IO0_PIN PINNUM(0, 6)
#define MOTA_QSPI_IO1_PIN PINNUM(0, 26)
#define MOTA_QSPI_IO2_PIN PINNUM(1, 4)
#define MOTA_QSPI_IO3_PIN PINNUM(1, 2)

#define BLEDIS_MANUFACTURER "B and Q"
#define BLEDIS_MODEL "Nano G2 Ultra"

// Retain the exact manufacturer factory HEX identity, confirmed in both CF2
// and its USB device descriptor. Do not copy the generic application HWIDs
// or the unconfirmed Adafruit PID proposed in another bootloader's draft PR.
// Keep that same factory identity in CDC-only mode, without allocating a PID.
#define USB_DESC_VID 0x4251
#define USB_DESC_UF2_PID 0x8695
#define USB_DESC_CDC_ONLY_PID 0x8695

#define UF2_PRODUCT_NAME "B and Q Nano G2 Ultra"
#define UF2_VOLUME_LABEL "NANOG2BOOT"
#define UF2_BOARD_ID "nRF52840-BQ-rev1"
#define UF2_INDEX_URL "https://wiki.bqvoy.com/en/meshtastic/nano-g2-ultra"

#endif // _NANO_G2_ULTRA_H
