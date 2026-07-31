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

#ifndef _HELTEC_T096_H
#define _HELTEC_T096_H

#define _PINNUM(port, pin)    ((port)*32 + (pin))

/*------------------------------------------------------------------*/
/* LED
 *------------------------------------------------------------------*/
#define LEDS_NUMBER           1
#define LED_PRIMARY_PIN       _PINNUM(0, 28) // White, active high
#define LED_STATE_ON          1

#define BOARD_RGB_BRIGHTNESS  0x040404

/*------------------------------------------------------------------*/
/* BUTTON
 * T096 has one user button. Mapping both bootloader actions to it is
 * intentional and follows the existing T114 configuration.
 *------------------------------------------------------------------*/
#define BUTTON_DFU            _PINNUM(1, 10)
#define BUTTON_DFU_OTA        _PINNUM(1, 10)
#define BUTTON_PULL           NRF_GPIO_PIN_PULLUP

//--------------------------------------------------------------------+
// Display (ST7735S, 160x80)
//--------------------------------------------------------------------+

// Vext_Ctrl powers the display.
#define DISPLAY_VSENSOR_PIN   _PINNUM(0, 26)
#define DISPLAY_VSENSOR_ON    1

#define DISPLAY_CONTROLLER_ST7735

#define DISPLAY_PIN_SCK       _PINNUM(0, 20)
#define DISPLAY_PIN_MOSI      _PINNUM(0, 17)
#define DISPLAY_PIN_CS        _PINNUM(0, 22)
#define DISPLAY_PIN_DC        _PINNUM(0, 15)
#define DISPLAY_PIN_RST       _PINNUM(0, 13)
#define DISPLAY_PIN_BL        _PINNUM(1, 12)
#define DISPLAY_BL_ON         0

#define DISPLAY_WIDTH         160
#define DISPLAY_HEIGHT        80

// USB facing left.
#define DISPLAY_COL_OFFSET    24
#define DISPLAY_ROW_OFFSET    0
#define DISPLAY_MADCTL        (TFT_MADCTL_MY | TFT_MADCTL_BGR)
#define DISPLAY_VSCSAD        0

#define DISPLAY_TITLE         "n5262G"
#define BANNER_TEXT           "OTAFIX / oltaco"

//--------------------------------------------------------------------+
// BLE OTA
//--------------------------------------------------------------------+
#define BLEDIS_MANUFACTURER   "Heltec Automation"
#define BLEDIS_MODEL          "HT-n5262G"

//--------------------------------------------------------------------+
// USB
// Heltec's stock T096 bootloader shares PID 0x0071 with the T114.
// Matching it permits an out-of-box bootloader update via UF2.
//--------------------------------------------------------------------+
#define USB_DESC_VID           0x239A
#define USB_DESC_UF2_PID       0x0071
#define USB_DESC_CDC_ONLY_PID  0x0071

//------------- UF2 -------------//
#define UF2_PRODUCT_NAME      "HT-n5262G"
#define UF2_VOLUME_LABEL      "HT-n5262G"
#define UF2_BOARD_ID          "HT-n5262G"
#define UF2_INDEX_URL         "https://heltec.org/project/t096/"

#endif
