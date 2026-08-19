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

#ifndef _WISCORE_RAK3401_H
#define _WISCORE_RAK3401_H

// The WisBlock base supplies VDDH; configure the nRF52840 GPIO rail for 3.3 V.
#define UICR_REGOUT0_VALUE UICR_REGOUT0_VOUT_3V3

#define _PINNUM(port, pin) ((port) * 32 + (pin))

/*------------------------------------------------------------------*/
/* LED
 *------------------------------------------------------------------*/
#define LEDS_NUMBER       2
#define LED_PRIMARY_PIN   _PINNUM(1, 3) // Green, active high
#define LED_SECONDARY_PIN _PINNUM(1, 4) // Blue, active high
#define LED_STATE_ON      1

/*------------------------------------------------------------------*/
/* BUTTON
 * The base-board reset switch is not a GPIO button. Recovery remains
 * available through double-reset, USB, and application-requested BLE DFU.
 *------------------------------------------------------------------*/

//--------------------------------------------------------------------+
// BLE OTA
//--------------------------------------------------------------------+
#define BLEDIS_MANUFACTURER "RAKwireless"
#define BLEDIS_MODEL        "WisBlock RAK3401"

//--------------------------------------------------------------------+
// USB
// RAK3401 ships with the RAK4631 bootloader and its 0x239A:0x0029 UF2 identity.
// Retain that identity as an explicit legacy compatibility exception for
// out-of-box updates; this reserved Adafruit VID is not a template for new
// board targets. The unique 3401_DFU manifest identity protects later updates.
//--------------------------------------------------------------------+
#define USB_DESC_VID          0x239A
#define USB_DESC_UF2_PID      0x0029
#define USB_DESC_CDC_ONLY_PID 0x002A

//------------- UF2 -------------//
#define UF2_PRODUCT_NAME "WisBlock RAK3401"
#define UF2_VOLUME_LABEL "RAK3401"
#define UF2_BOARD_ID     "WisBlock-RAK3401"
#define UF2_INDEX_URL    "https://docs.rakwireless.com/product-categories/wisblock/rak3401/overview/"

#endif
