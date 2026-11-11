#!/usr/bin/env python3
"""Exercise the production DFU entry function after a completed settings phase."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from ble_recovery_test import declaration, function

ROOT = Path(__file__).resolve().parents[1]


class DfuSessionStartTest(unittest.TestCase):
    def test_completed_status_cannot_end_a_new_session(self):
        source = (ROOT / "lib/sdk11/components/libraries/bootloader_dfu/bootloader.c").read_text()
        entry = re.search(r"uint32_t bootloader_dfu_start\([^\n]+\)\s*\{.*?^\}",
                          source, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(entry)
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#define NRF_SUCCESS 0u
#define APP_TIMER_MODE_SINGLE_SHOT 0u
#define VERIFY_SUCCESS(code) do { if ((code) != NRF_SUCCESS) return (code); } while (0)
'''
        harness += declaration(source, "bootloader_status_t;")
        harness += r'''
static bootloader_status_t m_update_status = BOOTLOADER_APP_COMPLETE;
static bool m_cancel_timeout_on_usb, m_usb_was_mounted;
static bool m_startup_dfu_has_activity;
static int _dfu_startup_timer;
static unsigned ble_starts, serial_starts, waits, timers, init_error;
'''
        harness += function(source, "bool bootloader_dfu_app_update_complete(void)")
        harness += r'''
static uint32_t dfu_init(void) {
  assert(m_update_status == BOOTLOADER_UPDATING);
  assert(!m_usb_was_mounted && !m_startup_dfu_has_activity && !bootloader_dfu_app_update_complete());
  return init_error;
}
static uint32_t dfu_transport_ble_update_start(void) { ++ble_starts; return NRF_SUCCESS; }
static uint32_t dfu_transport_serial_update_start(void) { ++serial_starts; return NRF_SUCCESS; }
static void dfu_startup_timer_handler(void *context) { (void)context; }
static uint32_t app_timer_create(int *timer, unsigned mode, void (*handler)(void *)) {
  (void)timer; (void)mode; (void)handler; ++timers; return NRF_SUCCESS;
}
static uint32_t app_timer_start(int timer, uint32_t ticks, void *context) {
  (void)timer; (void)context; assert(ticks == 100); return NRF_SUCCESS;
}
static uint32_t dfu_timeout_ticks(uint32_t ms) { return ms; }
static void wait_for_events(void) {
  assert(m_update_status == BOOTLOADER_UPDATING);
  ++waits;
  m_update_status = BOOTLOADER_COMPLETE;
}
'''
        harness += entry.group(0) + r'''
int main(void) {
  const bootloader_status_t prior[] = {BOOTLOADER_COMPLETE, BOOTLOADER_APP_COMPLETE};
  for (unsigned previous = 0; previous != 2; ++previous) {
    for (unsigned ota = 0; ota < 2; ++ota) {
      for (unsigned timed = 0; timed < 2; ++timed) {
        for (unsigned cancel = 0; cancel < 2; ++cancel) {
          m_update_status = prior[previous];
          m_usb_was_mounted = m_startup_dfu_has_activity = true;
          unsigned before = waits;
          assert(bootloader_dfu_start(ota != 0, timed ? 100 : 0, cancel != 0) == NRF_SUCCESS);
          assert(waits == before + 1);
          assert(m_cancel_timeout_on_usb == (cancel && !ota));
        }
      }
    }
  }
  assert(ble_starts == 8 && serial_starts == 8 && waits == 16 && timers == 4);
  m_update_status = BOOTLOADER_APP_COMPLETE;
  init_error = 123;
  assert(bootloader_dfu_start(true, 0, false) == 123);
  assert(waits == 16 && ble_starts == 8 && !bootloader_dfu_app_update_complete());
}
'''
        with tempfile.TemporaryDirectory(prefix="otafix-dfu-session-") as directory:
            binary = Path(directory) / ("session.exe" if os.name == "nt" else "session")
            subprocess.run([os.environ.get("CC", "gcc"), "-std=c11", "-O2", "-Wall", "-Wextra",
                            "-Werror", "-x", "c", "-", "-o", str(binary)],
                           input=harness, text=True, check=True)
            subprocess.run([str(binary)], check=True)

    def test_polling_and_normal_wait_service_retries_from_foreground(self):
        main = (ROOT / "src/main.c").read_text()
        soc = re.search(r"uint32_t proc_soc\(void\)\s*\{.*?^\}", main, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(soc)
        self.assertLess(soc.group(0).index("pstorage_sys_event_handler"),
                        soc.group(0).index("pstorage_process();"))
        driver = (ROOT / "lib/sdk11/components/libraries/bootloader_dfu/bootloader.c").read_text()
        waiting = driver[driver.index("static void wait_for_events(void)"):
                         driver.index("bool bootloader_app_is_valid(void)")]
        self.assertIn("pstorage_process();", waiting)
        self.assertLess(waiting.index("m_update_status == BOOTLOADER_COMPLETE"),
                        waiting.index("pstorage_process();"))

    def test_real_wait_loop_services_three_active_states_and_exits_five_terminal_states(self):
        source = (ROOT / "lib/sdk11/components/libraries/bootloader_dfu/bootloader.c").read_text()
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define NRF_WDT ((void *)1)
#define CFG_TUD_MSC 0
'''
        harness += declaration(source, "bootloader_status_t;")
        harness += r'''
static bootloader_status_t m_update_status;
static unsigned scheduled, storage, polls, reloads;
static bool watchdog_running;
static bool nrf_wdt_started(void *wdt) { assert(wdt == NRF_WDT); return watchdog_running; }
static void nrf_wdt_reload_request_set(void *wdt, unsigned channel) {
  assert(wdt == NRF_WDT && channel < 8); ++reloads;
}
static void app_sched_execute(void) {
  ++scheduled;
  assert(scheduled <= 2);
  /* End after one active iteration, so a wrong classification cannot hang the test. */
  if (scheduled == 2) m_update_status = BOOTLOADER_COMPLETE;
}
static void pstorage_process(void) {
  assert(m_update_status == BOOTLOADER_UPDATING ||
         m_update_status == BOOTLOADER_SETTINGS_SAVING ||
         m_update_status == BOOTLOADER_APP_SETTINGS_SAVING);
  assert(scheduled == 1); ++storage;
}
#ifdef SECURE_DFU_TEST
static void dfu_transport_ble_poll(void) { assert(storage == 1); ++polls; }
#endif
#ifdef NRF_USBD
#define POWER_USBREGSTATUS_VBUSDETECT_Msk 1u
static struct { uint32_t USBREGSTATUS; } power = {1};
#define NRF_POWER (&power)
static bool m_cancel_timeout_on_usb = true, m_usb_was_mounted = true;
static unsigned usb_tasks, usb_flushes;
static bool tusb_inited(void) { return true; }
static void tud_task(void) { ++usb_tasks; }
static void tud_cdc_write_flush(void) { ++usb_flushes; }
static void bootloader_timeout_startup_dfu(void) { assert(!"USB still has VBUS"); }
#endif
'''
        harness += function(source, "static void wait_for_events(void)")
        harness += r'''
int main(void) {
  const bootloader_status_t states[] = {BOOTLOADER_UPDATING, BOOTLOADER_SETTINGS_SAVING,
    BOOTLOADER_COMPLETE, BOOTLOADER_TIMEOUT, BOOTLOADER_SYS_RESET, BOOTLOADER_RESET_TO_SELF,
    BOOTLOADER_APP_COMPLETE, BOOTLOADER_APP_SETTINGS_SAVING};
  for (unsigned watchdog = 0; watchdog != 2; ++watchdog) {
    for (unsigned index = 0; index != sizeof(states) / sizeof(states[0]); ++index) {
      m_update_status = states[index]; watchdog_running = watchdog != 0;
      scheduled = storage = polls = reloads = 0;
#ifdef NRF_USBD
      usb_tasks = usb_flushes = 0;
#endif
      const bool active = states[index] == BOOTLOADER_UPDATING ||
                          states[index] == BOOTLOADER_SETTINGS_SAVING ||
                          states[index] == BOOTLOADER_APP_SETTINGS_SAVING;
      wait_for_events();
      assert(scheduled == (active ? 2u : 1u));
      assert(storage == (active ? 1u : 0u));
#ifdef SECURE_DFU_TEST
      assert(polls == (active ? 1u : 0u));
#else
      assert(polls == 0);
#endif
      assert(reloads == (watchdog ? scheduled * 8u : 0u));
#ifdef NRF_USBD
      assert(usb_tasks == scheduled && usb_flushes == scheduled);
#endif
    }
  }
  return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="otafix-dfu-wait-") as directory:
            for secure in (False, True):
                for usb in (False, True):
                    with self.subTest(secure=secure, usb=usb):
                        binary = Path(directory) / ("wait.exe" if os.name == "nt" else "wait")
                        flags = (["-DSECURE_DFU_TEST"] if secure else []) + (["-DNRF_USBD"] if usb else [])
                        subprocess.run([os.environ.get("CC", "gcc"), "-std=c11", "-O2", "-Wall", "-Wextra",
                                        "-Werror", *flags, "-x", "c", "-", "-o", str(binary)],
                                       input=harness, text=True, check=True)
                        subprocess.run([str(binary)], check=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
