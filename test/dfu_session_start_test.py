#!/usr/bin/env python3
"""Exercise the production DFU entry function after a completed settings phase."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

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
#define BOOTLOADER_UPDATING 0u
#define BOOTLOADER_COMPLETE 1u
#define APP_TIMER_MODE_SINGLE_SHOT 0u
#define VERIFY_SUCCESS(code) do { if ((code) != NRF_SUCCESS) return (code); } while (0)
static unsigned m_update_status = BOOTLOADER_COMPLETE;
static bool m_cancel_timeout_on_usb, m_usb_was_mounted;
static bool m_startup_dfu_has_activity, m_app_update_complete;
static int _dfu_startup_timer;
static unsigned ble_starts, serial_starts, waits, timers, init_error;
static uint32_t dfu_init(void) {
  assert(m_update_status == BOOTLOADER_UPDATING);
  assert(!m_usb_was_mounted && !m_startup_dfu_has_activity && !m_app_update_complete);
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
  for (unsigned ota = 0; ota < 2; ++ota) {
    for (unsigned timed = 0; timed < 2; ++timed) {
      for (unsigned cancel = 0; cancel < 2; ++cancel) {
        m_update_status = BOOTLOADER_COMPLETE;
        m_usb_was_mounted = m_startup_dfu_has_activity = m_app_update_complete = true;
        unsigned before = waits;
        assert(bootloader_dfu_start(ota != 0, timed ? 100 : 0, cancel != 0) == NRF_SUCCESS);
        assert(waits == before + 1);
        assert(m_cancel_timeout_on_usb == (cancel && !ota));
      }
    }
  }
  assert(ble_starts == 4 && serial_starts == 4 && waits == 8 && timers == 2);
  init_error = 123;
  assert(bootloader_dfu_start(true, 0, false) == 123);
  assert(waits == 8 && ble_starts == 4);
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


if __name__ == "__main__":
    unittest.main()
