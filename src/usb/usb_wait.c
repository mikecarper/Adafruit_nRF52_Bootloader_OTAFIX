/*
 * The MIT License (MIT)
 *
 * Copyright (c) 2026 Mike Carper
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

#include "usb_wait.h"

#ifdef USB_WAIT_HOST_TEST

extern bool usb_wait_vbus_present(void);
extern void usb_wait_task(void);
extern bool usb_wait_mounted(void);
extern void usb_wait_feed_watchdog(void);
extern void usb_wait_delay_ms(uint32_t delay_ms);

#else

#include "nrfx.h"
#include "nrf_usbd.h"
#include "nrf_wdt.h"
#include "tusb.h"

static bool usb_wait_vbus_present(void) {
  return (NRF_POWER->USBREGSTATUS & POWER_USBREGSTATUS_VBUSDETECT_Msk) != 0;
}

static void usb_wait_task(void) {
  tud_task();
}

static bool usb_wait_mounted(void) {
  return tud_mounted();
}

static void usb_wait_feed_watchdog(void) {
  // WDT configuration survives a reset, so keep feeding a watchdog that was
  // started by the previous application while waiting for USB enumeration.
  if (nrf_wdt_started(NRF_WDT)) {
    for (uint8_t i = 0; i < 8; i++) {
      nrf_wdt_reload_request_set(NRF_WDT, i);
    }
  }
}

static void usb_wait_delay_ms(uint32_t delay_ms) {
  NRFX_DELAY_MS(delay_ms);
}

#endif

bool usb_wait_for_mount(uint32_t timeout_ms) {
  // No VBUS means battery-only power, so do not delay the BLE recovery path.
  // VBUS only proves that USB power is present; a mounted TinyUSB device proves
  // that an active USB data host is attached and can be used for DFU.
  if (!usb_wait_vbus_present()) {
    return false;
  }

  for (uint32_t elapsed_ms = 0; elapsed_ms < timeout_ms; elapsed_ms++) {
    usb_wait_task();

    if (!usb_wait_vbus_present()) {
      return false;
    }

    if (usb_wait_mounted()) {
      return true;
    }

    usb_wait_feed_watchdog();
    usb_wait_delay_ms(1);
  }

  // Give a host that completed enumeration exactly at the deadline one final
  // TinyUSB poll, matching the normal per-millisecond polling behavior.
  usb_wait_task();
  return usb_wait_vbus_present() && usb_wait_mounted();
}
