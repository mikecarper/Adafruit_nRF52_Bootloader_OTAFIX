/*
 * The MIT License (MIT)
 *
 * Copyright (c) 2026 MeshCore contributors
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

#ifndef _KEEPTEEN_LT1_H
#define _KEEPTEEN_LT1_H

#define _PINNUM(port, pin) ((port) * 32 + (pin))

/*------------------------------------------------------------------*/
/* LED
 *------------------------------------------------------------------*/
#define LEDS_NUMBER      1
#define LED_PRIMARY_PIN  _PINNUM(0, 15) // Blue, active high
#define LED_STATE_ON     1
#define NEOPIXELS_NUMBER 0

/*------------------------------------------------------------------*/
/* BUTTON
 *------------------------------------------------------------------*/
#define BUTTON_DFU     _PINNUM(1, 0)
#define BUTTON_DFU_OTA _PINNUM(1, 0)
#define BUTTON_PULL    NRF_GPIO_PIN_PULLUP

//--------------------------------------------------------------------+
// BLE OTA
//--------------------------------------------------------------------+
#define BLEDIS_MANUFACTURER "Keepteen"
#define BLEDIS_MODEL        "LT1"

//--------------------------------------------------------------------+
// USB
// LT1 firmware recognizes the ProMicro-compatible 0x239A:0x00B3 factory
// bootloader. Keep the bootstrap identity while using an exact LT1 manifest
// identity for all subsequent signed bootloader updates.
//--------------------------------------------------------------------+
#define USB_DESC_VID          0x239A
#define USB_DESC_UF2_PID      0x00B3
#define USB_DESC_CDC_ONLY_PID 0x00B3

//------------- UF2 -------------//
#define UF2_PRODUCT_NAME "Keepteen LT1"
#define UF2_VOLUME_LABEL "KEEPTEENLT1"
#define UF2_BOARD_ID     "Keepteen-LT1"
#define UF2_INDEX_URL    "https://www.keepteen.com/"

#endif
