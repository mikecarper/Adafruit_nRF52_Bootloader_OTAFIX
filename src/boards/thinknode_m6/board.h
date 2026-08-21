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

#ifndef _THINKNODE_M6_H
#define _THINKNODE_M6_H

#define _PINNUM(port, pin)    ((port)*32 + (pin))

/*------------------------------------------------------------------*/
/* LED
 *------------------------------------------------------------------*/
#define LEDS_NUMBER       1
#define LED_PRIMARY_PIN   _PINNUM(0, 7) // Blue
#define LED_STATE_ON      1

/*------------------------------------------------------------------*/
/* BUTTON
 *------------------------------------------------------------------*/
#define BUTTON_DFU        _PINNUM(0, 17)  // user button
#define BUTTON_DFU_OTA    _PINNUM(0, 17)  // hold on boot to enter OTA DFU mode
#define BUTTON_PULL       NRF_GPIO_PIN_PULLUP

// On-board QSPI flash used as the raw MeshCore repeater OTA store.
#define MOTA_QSPI_SCK_PIN          _PINNUM(1, 3)
#define MOTA_QSPI_CSN_PIN          _PINNUM(0, 23)
#define MOTA_QSPI_IO0_PIN          _PINNUM(1, 1)
#define MOTA_QSPI_IO1_PIN          _PINNUM(1, 2)
#define MOTA_QSPI_IO2_PIN          _PINNUM(1, 4)
#define MOTA_QSPI_IO3_PIN          _PINNUM(1, 5)
#define MOTA_QSPI_POWER_PIN        _PINNUM(0, 21)
#define MOTA_QSPI_POWER_ACTIVE     1

//--------------------------------------------------------------------+
// BLE OTA
//--------------------------------------------------------------------+
#define BLEDIS_MANUFACTURER  "ELECROW"
#define BLEDIS_MODEL         "ThinkNodeM6"

//--------------------------------------------------------------------+
// USB
//--------------------------------------------------------------------+
#define USB_DESC_VID           0x239A
#define USB_DESC_UF2_PID       0x00DA
#define USB_DESC_CDC_ONLY_PID  0x00DA

#define UF2_PRODUCT_NAME  "ELECROW ThinkNodeM6"
#define UF2_VOLUME_LABEL  "ThinkNodeM6"
#define UF2_BOARD_ID      "nRF52840-ThinkNodeM6-v1"
#define UF2_INDEX_URL     "https://www.elecrow.com"

#endif // _THINKNODE_M6_H
