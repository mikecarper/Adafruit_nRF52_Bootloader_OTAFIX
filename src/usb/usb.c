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
#include "tusb.h"
#include "usb_desc.h"
#include "usb_wait.h"

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
// Read from USB/POWER interrupt context and written from the bootloader's main
// context.  Volatile keeps the transport gate observable across that boundary;
// usb_teardown() additionally disables USBD_IRQn before lowering it.
static volatile bool _usb_transport_active = false;

bool usb_transport_active(void) {
  return _usb_transport_active;
}

// power callback when SD is not enabled
static void power_event_handler(nrfx_power_usb_evt_t event) {
  if (_usb_transport_active) {
    tusb_hal_nrf_power_event((uint32_t) event);
  }
}

// Forward USB interrupt events to TinyUSB IRQ Handler
void USBD_IRQHandler(void) {
  if (_usb_transport_active) {
    tud_int_handler(0);
  }
}

//------------- IMPLEMENTATION -------------//
void usb_init(bool cdc_only) {
  _usb_transport_active = true;

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

void usb_teardown(void) {
  // A later BLE SoftDevice start can emit USB DETECTED/READY events while VBUS
  // remains present. Mark the transport inactive before simulating removal so
  // those SOC events cannot resurrect a TinyUSB stack that DFU already left.
  // Disable the peripheral IRQ first: if an uncleared USBD event preempted after
  // the gate was lowered, the inactive handler would return without servicing
  // it and the level-sensitive IRQ could immediately repend/tail-chain.
  NVIC_DisableIRQ(USBD_IRQn);
  NVIC_ClearPendingIRQ(USBD_IRQn);
  _usb_transport_active = false;
  __DMB();

  // Simulate an disconnect which cause pullup disable, USB perpheral disable and hclk disable
  tusb_hal_nrf_power_event(NRFX_POWER_USB_EVT_REMOVED);
  NVIC_ClearPendingIRQ(USBD_IRQn);

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
#if CFG_TUD_MSC
  // A configured/remounted USB volume is an explicit boundary between UF2
  // copies. Do not infer new sessions from ordinary FAT/SCSI traffic.
  uf2_write_session_reset();
#endif
  led_state(STATE_USB_MOUNTED);
  bootloader_mark_usb_mounted();
}

void tud_umount_cb(void) {
#if CFG_TUD_MSC
  uf2_write_session_reset();
#endif
  led_state(STATE_USB_UNMOUNTED);
}
