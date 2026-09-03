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

#ifndef PCA10056_H
#define PCA10056_H

/*------------------------------------------------------------------*/
/* LED
 *------------------------------------------------------------------*/
#define LEDS_NUMBER       2
#define LED_PRIMARY_PIN   13
#define LED_SECONDARY_PIN 14
#define LED_STATE_ON      0

/*------------------------------------------------------------------*/
/* BUTTON
 *------------------------------------------------------------------*/
#define BUTTON_DFU     11
#define BUTTON_DFU_OTA 12
#define BUTTON_PULL    NRF_GPIO_PIN_PULLUP

// On-board MX25R6435F QSPI flash used as the raw MeshCore OTA store.
#define MOTA_QSPI_SCK_PIN            19
#define MOTA_QSPI_CSN_PIN            17
#define MOTA_QSPI_IO0_PIN            20
#define MOTA_QSPI_IO1_PIN            21
#define MOTA_QSPI_IO2_PIN            22
#define MOTA_QSPI_IO3_PIN            23
#define MOTA_QSPI_SCK_FREQ           NRF_QSPI_FREQ_32MDIV4 // 8 MHz
#define MOTA_QSPI_JEDEC_MANUFACTURER 0xC2u
#define MOTA_QSPI_JEDEC_MEMORY_TYPE  0x28u
#define MOTA_QSPI_JEDEC_CAPACITY     0x17u

//--------------------------------------------------------------------+
// BLE OTA
//--------------------------------------------------------------------+
#define BLEDIS_MANUFACTURER "Nordic"
#define BLEDIS_MODEL        "PCA10056"

//--------------------------------------------------------------------+
// USB
//--------------------------------------------------------------------+

// Legacy Adafruit-assigned identity inherited from the upstream PCA10056
// target. This is not a template for new third-party assignments.
#define USB_DESC_VID          0x239A
#define USB_DESC_UF2_PID      0x00DA
#define USB_DESC_CDC_ONLY_PID 0x00DA

#define UF2_PRODUCT_NAME "Nordic nRF52840 DK"
#define UF2_VOLUME_LABEL "PCA10056"
#define UF2_BOARD_ID     "nRF52840-pca10056-v1"
#define UF2_INDEX_URL    "https://www.nordicsemi.com/Products/Development-hardware/nRF52840-DK"

#endif // PCA10056_H
