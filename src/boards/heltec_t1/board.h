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

#ifndef _HELTEC_T1_H
#define _HELTEC_T1_H

#define _PINNUM(port, pin) ((port) * 32 + (pin))

/*------------------------------------------------------------------*/
/* LED
 *------------------------------------------------------------------*/
#define LEDS_NUMBER          1
#define LED_PRIMARY_PIN      _PINNUM(0, 16) // White, active low
#define LED_STATE_ON         0

#define BOARD_RGB_BRIGHTNESS 0x040404

/*------------------------------------------------------------------*/
/* BUTTON
 *------------------------------------------------------------------*/
#define BUTTON_DFU     _PINNUM(1, 10)
#define BUTTON_DFU_OTA _PINNUM(0, 14)
#define BUTTON_PULL    NRF_GPIO_PIN_PULLUP

//--------------------------------------------------------------------+
// Display (ST7735S, 160x80)
//--------------------------------------------------------------------+

// VTFT_Ctrl powers the display.
#define DISPLAY_VSENSOR_PIN _PINNUM(0, 13)
#define DISPLAY_VSENSOR_ON  0

#define DISPLAY_CONTROLLER_ST7735

#define DISPLAY_PIN_SCK  _PINNUM(1, 0)
#define DISPLAY_PIN_MOSI _PINNUM(0, 24)
#define DISPLAY_PIN_CS   _PINNUM(0, 12)
#define DISPLAY_PIN_DC   _PINNUM(0, 22)
#define DISPLAY_PIN_RST  _PINNUM(0, 20)
#define DISPLAY_PIN_BL   _PINNUM(0, 15)
#define DISPLAY_BL_ON    0

#define DISPLAY_WIDTH    160
#define DISPLAY_HEIGHT   80

// Define DISPLAY_USB_FACING_DOWN at build time for the alternate mounting.
#if defined(DISPLAY_USB_FACING_DOWN)
  #define DISPLAY_COL_OFFSET 52
  #define DISPLAY_ROW_OFFSET 40
  #define DISPLAY_MADCTL     (TFT_MADCTL_MY | TFT_MADCTL_BGR)
#else
  #define DISPLAY_COL_OFFSET 24
  #define DISPLAY_ROW_OFFSET 0
  #define DISPLAY_MADCTL     (TFT_MADCTL_MX | TFT_MADCTL_BGR)
#endif
#define DISPLAY_VSCSAD 0

#define DISPLAY_TITLE  "T1"
#define BANNER_TEXT    "OTAFIX / oltaco"

// Compact 160x80 screen layout.
#define SCREEN_BAR1_Y          0
#define SCREEN_BAR1_H          32
#define SCREEN_BAR2_Y          32
#define SCREEN_BAR2_H          36
#define SCREEN_BAR3_Y          68
#define SCREEN_BAR3_H          12
#define SCREEN_TITLE_Y         1
#define SCREEN_VERSION_Y       24
#define SCREEN_BLE_OTA_Y       38
#define SCREEN_BANNER_Y        70
#define SCREEN_LARGE_FONT_SIZE 3
#define SCREEN_DRAG_Y          34
#define SCREEN_DRAG_X          4
#define SCREEN_PENDRIVE_LOGO_X 124
#define SCREEN_HIDE_LABELS

//--------------------------------------------------------------------+
// BLE OTA
//--------------------------------------------------------------------+
#define BLEDIS_MANUFACTURER "Heltec Automation"
#define BLEDIS_MODEL        "Mesh Node T1"

//--------------------------------------------------------------------+
// USB
// Heltec's factory T1 bootloader uses Adafruit CLUE's 0x239A:0x0071 identity.
// Retain it as an explicit legacy compatibility exception for out-of-box UF2
// updates; this reserved Adafruit VID is not a template for new board targets.
//--------------------------------------------------------------------+
#define USB_DESC_VID          0x239A
#define USB_DESC_UF2_PID      0x0071
#define USB_DESC_CDC_ONLY_PID 0x0071

//------------- UF2 -------------//
#define UF2_PRODUCT_NAME "Heltec Mesh Node T1"
#define UF2_VOLUME_LABEL "HELTEC-T1"
#define UF2_BOARD_ID     "Heltec-Mesh-Node-T1"
#define UF2_INDEX_URL    "https://heltec.org/project/mesh-node-t1/"

#endif
