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

#include "nrfx.h"
#include "nrfx_power.h"
#include "nrf_sdm.h"
#include "nrf_soc.h"

#include "nrf_usbd.h"
#include "nrf_wdt.h"
#include "tusb.h"
#include "usb_desc.h"

#include "uf2/uf2.h"
#include "boards.h"
#include "bootloader.h"

//--------------------------------------------------------------------+
// MACRO TYPEDEF CONSTANT ENUM DECLARATION
//--------------------------------------------------------------------+

/* tinyusb function that handles power event (detected, ready, removed)
 * We must call it within SD's SOC event handler, or set it as power event handler if SD is not enabled. */
extern void tusb_hal_nrf_power_event(uint32_t event);

static bool _nrfx_power_initialized = false;

// power callback when SD is not enabled
static void power_event_handler(nrfx_power_usb_evt_t event) {
  tusb_hal_nrf_power_event((uint32_t) event);
}

// Forward USB interrupt events to TinyUSB IRQ Handler
void USBD_IRQHandler(void) {
  tud_int_handler(0);
}

//------------- IMPLEMENTATION -------------//
void usb_init(bool cdc_only) {
  // 0, 1 is reserved for SD
  NVIC_SetPriority(USBD_IRQn, 2);

  // USB power may already be ready at this time -> no event generated
  // We need to invoke the handler based on the status initially
  uint32_t usb_reg;
  uint8_t sd_en = false;

  if (is_sd_existed()) {
    sd_softdevice_is_enabled(&sd_en);
  }

  if (sd_en) {
    sd_power_usbdetected_enable(true);
    sd_power_usbpwrrdy_enable(true);
    sd_power_usbremoved_enable(true);
    sd_power_usbregstatus_get(&usb_reg);
  } else {
    // Power module init
    const nrfx_power_config_t pwr_cfg = {0};
    _nrfx_power_initialized = (nrfx_power_init(&pwr_cfg) == NRFX_SUCCESS);

    // Register USB power handler
    const nrfx_power_usbevt_config_t config = {.handler = power_event_handler};
    nrfx_power_usbevt_init(&config);

    nrfx_power_usbevt_enable();

    usb_reg = NRF_POWER->USBREGSTATUS;
  }

  if (usb_reg & POWER_USBREGSTATUS_VBUSDETECT_Msk) {
    tusb_hal_nrf_power_event(NRFX_POWER_USB_EVT_DETECTED);
  }

  if (usb_reg & POWER_USBREGSTATUS_OUTPUTRDY_Msk) {
    tusb_hal_nrf_power_event(NRFX_POWER_USB_EVT_READY);
  }

  usb_desc_init(cdc_only);
#if CFG_TUD_MSC
  uf2_init();
#endif
  tusb_init();

  #ifdef DISPLAY_PIN_SCK
  board_display_init();
  screen_draw_drag();
  #endif
}

bool usb_wait_for_mount(uint32_t timeout_ms) {
  // VBUS only proves that USB power is present. A configured TinyUSB device proves
  // that an active USB host is attached and can be used for DFU.
  if (!(NRF_POWER->USBREGSTATUS & POWER_USBREGSTATUS_VBUSDETECT_Msk)) {
    return false;
  }

  for (uint32_t elapsed_ms = 0; elapsed_ms < timeout_ms; elapsed_ms++) {
    tud_task();

    if (tud_mounted()) {
      return true;
    }

    if (!(NRF_POWER->USBREGSTATUS & POWER_USBREGSTATUS_VBUSDETECT_Msk)) {
      return false;
    }

    // WDT configuration survives a reset, so keep feeding a watchdog that was
    // started by the previous application while waiting for USB enumeration.
    if (nrf_wdt_started(NRF_WDT)) {
      for (uint8_t i = 0; i < 8; i++) {
        nrf_wdt_reload_request_set(NRF_WDT, i);
      }
    }

    NRFX_DELAY_MS(1);
  }

  tud_task();
  return tud_mounted();
}

void usb_teardown(void) {
  // Simulate an disconnect which cause pullup disable, USB perpheral disable and hclk disable
  tusb_hal_nrf_power_event(NRFX_POWER_USB_EVT_REMOVED);

  // A USB probe can be followed by enabling the SoftDevice for BLE. Release the
  // direct nrfx POWER interrupt first so the SoftDevice can own that peripheral.
  if (_nrfx_power_initialized) {
    nrfx_power_usbevt_disable();
    nrfx_power_uninit();
    _nrfx_power_initialized = false;
  }
}

//--------------------------------------------------------------------+
// tinyusb callbacks
//--------------------------------------------------------------------+
void tud_mount_cb(void) {
  led_state(STATE_USB_MOUNTED);
  bootloader_mark_usb_mounted();
}

void tud_umount_cb(void) {
  led_state(STATE_USB_UNMOUNTED);
}
