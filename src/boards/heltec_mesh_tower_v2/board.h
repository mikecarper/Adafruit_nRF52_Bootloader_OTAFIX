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

#ifndef _HELTEC_MESH_TOWER_V2_H
#define _HELTEC_MESH_TOWER_V2_H

#define _PINNUM(port, pin) ((port) * 32 + (pin))

/*------------------------------------------------------------------*/
/* LED
 *------------------------------------------------------------------*/
#define LEDS_NUMBER      1
#define LED_PRIMARY_PIN  _PINNUM(1, 15) // Green, active low
#define LED_STATE_ON     0
#define NEOPIXELS_NUMBER 0

/*------------------------------------------------------------------*/
/* BUTTON
 *------------------------------------------------------------------*/
#define BUTTON_DFU     _PINNUM(1, 10)
#define BUTTON_DFU_OTA _PINNUM(1, 10)
#define BUTTON_PULL    NRF_GPIO_PIN_PULLUP

/*------------------------------------------------------------------*/
/* External watchdog
 *
 * The TPL5010-style watchdog remains powered across MCU resets. Feed it while
 * the bootloader waits for or applies an update so it cannot interrupt DFU.
 *------------------------------------------------------------------*/
#define EXTERNAL_WATCHDOG_DONE_PIN         _PINNUM(0, 9)
#define EXTERNAL_WATCHDOG_FEED_INTERVAL_MS (60UL * 1000UL)
#define EXTERNAL_WATCHDOG_FEED_PULSE_MS    1UL

//--------------------------------------------------------------------+
// BLE OTA
//--------------------------------------------------------------------+
#define BLEDIS_MANUFACTURER "Heltec Automation"
#define BLEDIS_MODEL        "HT-n5262"

//--------------------------------------------------------------------+
// USB
//
// The factory MeshTower V2 bootloader uses this legacy shared VID/PID in both
// its USB descriptor and CF2 bootloader board ID. Matching it is required for
// an out-of-box bootloader update via UF2; it is not a template for new boards.
//--------------------------------------------------------------------+
#define USB_DESC_VID          0x239A
#define USB_DESC_UF2_PID      0x0071
#define USB_DESC_CDC_ONLY_PID 0x0071

//------------- UF2 -------------//
#define UF2_PRODUCT_NAME "Heltec MeshTower V2"
#define UF2_VOLUME_LABEL "HT-n5262"
#define UF2_BOARD_ID     "HT-n5262"
#define UF2_INDEX_URL    "https://heltec.org/project/meshtower/"

#endif
