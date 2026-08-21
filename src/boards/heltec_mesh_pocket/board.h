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

#ifndef _HELTEC_MESH_POCKET_H
#define _HELTEC_MESH_POCKET_H

#define _PINNUM(port, pin) ((port) * 32 + (pin))

/*------------------------------------------------------------------*/
/* LED
 *------------------------------------------------------------------*/
#define LEDS_NUMBER      1
#define LED_PRIMARY_PIN  _PINNUM(0, 13) // Red, active low
#define LED_STATE_ON     0
#define NEOPIXELS_NUMBER 0

/*------------------------------------------------------------------*/
/* BUTTON
 *------------------------------------------------------------------*/
#define BUTTON_DFU     _PINNUM(1, 10)
#define BUTTON_DFU_OTA _PINNUM(1, 10)
#define BUTTON_PULL    NRF_GPIO_PIN_PULLUP

//--------------------------------------------------------------------+
// BLE OTA
//--------------------------------------------------------------------+
#define BLEDIS_MANUFACTURER "Heltec Automation"
#define BLEDIS_MODEL        "Mesh Pocket"

//--------------------------------------------------------------------+
// USB
// Heltec's official Heltec_nRF52 boards.txt lists 0x239A:0x0071 as the
// HT-n5262-e213 Mesh Pocket bootloader identity (the application is 0x8071).
// The unique MESH_POCKET_OTA manifest identity protects subsequent signed
// bootloader updates from other boards that shipped with the shared PID.
//--------------------------------------------------------------------+
#define USB_DESC_VID          0x239A
#define USB_DESC_UF2_PID      0x0071
#define USB_DESC_CDC_ONLY_PID 0x0071

//------------- UF2 -------------//
#define UF2_PRODUCT_NAME "Heltec Mesh Pocket"
#define UF2_VOLUME_LABEL "MESHPOCKET"
#define UF2_BOARD_ID     "Heltec-Mesh-Pocket"
#define UF2_INDEX_URL    "https://heltec.org/project/mesh-pocket/"

#endif
