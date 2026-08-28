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

#ifndef _GAT562_H
#define _GAT562_H

// GAT562 modules are powered through VDDH on the published carrier schematics.
#define UICR_REGOUT0_VALUE UICR_REGOUT0_VOUT_3V3

#define _PINNUM(port, pin) ((port) * 32 + (pin))

/*------------------------------------------------------------------*/
/* LED
 * The Tracker Pro, 30S Kit/Pod, and EVB carriers route the module's
 * LED1/LED2 outputs to active-high green and blue indicators. The solar
 * relay leaves these module pins unconnected, which is safe.
 *------------------------------------------------------------------*/
#define LEDS_NUMBER       2
#define LED_PRIMARY_PIN   _PINNUM(1, 3) // Green
#define LED_SECONDARY_PIN _PINNUM(1, 4) // Blue
#define LED_STATE_ON      1

/*------------------------------------------------------------------*/
/* BUTTON
 * The handheld carriers use NFC1/P0.09 for the side user button and
 * QSPI_CS/P0.26 for the joystick press. Holding both selects BLE OTA;
 * holding only the side button selects USB CDC/UF2. Other GAT562 carriers
 * can always use double reset or an application-requested DFU mode.
 *------------------------------------------------------------------*/
#define BUTTON_DFU     _PINNUM(0, 9)
#define BUTTON_DFU_OTA _PINNUM(0, 26)
#define BUTTON_PULL    NRF_GPIO_PIN_PULLUP

//--------------------------------------------------------------------+
// BLE OTA
//--------------------------------------------------------------------+
#define BLEDIS_MANUFACTURER "MTools Tec"
#define BLEDIS_MODEL        "GAT562"

//--------------------------------------------------------------------+
// USB
// Shipped GAT562 devices use the RAK4631-compatible Adafruit VID/PID.
// This legacy shared identity is retained for factory-bootloader UF2
// compatibility; the GAT562_DFU manifest identity protects later updates.
//--------------------------------------------------------------------+
#define USB_DESC_VID          0x239A
#define USB_DESC_UF2_PID      0x0029
#define USB_DESC_CDC_ONLY_PID 0x002A

//------------- UF2 -------------//
#define UF2_PRODUCT_NAME "MTools Tec GAT562"
#define UF2_VOLUME_LABEL "GAT562BOOT"
#define UF2_BOARD_ID     "GAT562-Family"
#define UF2_INDEX_URL    "https://github.com/gat-iot/GAT562-family"

#endif // _GAT562_H
