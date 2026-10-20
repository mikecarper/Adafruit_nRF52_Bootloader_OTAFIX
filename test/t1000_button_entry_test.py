#!/usr/bin/env python3
"""Run the real T1000 button reader and DFU decision with bounded host mocks."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, signature):
    start = source.index(signature)
    end = source.index("\n}", start) + 2
    return source[start:end]


class T1000ButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.binaries = {}
        main = (ROOT / "src/main.c").read_text()
        boards = (ROOT / "src/boards/boards.c").read_text()
        constants = main[main.index("#define DFU_MAGIC_SERIAL_ONLY_RESET"):
                         main.index("#define BOOTLOADER_VERSION_REGISTER")]
        harness = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#define PINNUM(p,n) ((p)*32+(n))
#define NRF_GPIO_PIN_PULLUP 3
#define NRF_GPIO_PIN_PULLDOWN 1
#include BOARD_HEADER
#include "dfu_entry.h"
#include "usb/usb_wait.h"
#if defined(REQUIRE_SINGLE_BUTTON) && defined(BUTTON_DFU_OTA)
#error "P0.18 is RESET, not a second T1000 user button"
#endif
#define DEFAULT_TO_OTA_DFU 1
#define POWER_RESETREAS_RESETPIN_Msk 1u
#define APP_ASKS_FOR_SINGLE_TAP_RESET() (single_tap)
static struct { uint32_t GPREGRET, RESETREAS; } power;
#define NRF_POWER (&power)
static uint32_t dbl_reset_word;
static uint32_t *dbl_reset_mem = &dbl_reset_word;
static bool _ota_dfu, _sd_inited, single_tap, host_mounts = true;
static uint32_t now_ms, held_until, gpio_reads, usb_calls, ble_calls, dfu_calls;
static uint32_t primary_reads, secondary_reads;
static uint32_t last_timeout;
static bool last_ota, last_cancel, release_after_qualification, second_held;
enum { STATE_USB_UNMOUNTED, STATE_BLE_DISCONNECTED };
static uint32_t nrf_gpio_pin_read(uint32_t pin) {
  gpio_reads++;
  bool pressed;
  if (pin == BUTTON_DFU) {
    primary_reads++;
    pressed = now_ms < held_until;
    if (release_after_qualification && now_ms >= 3000) held_until = 0;
#ifdef BUTTON_DFU_OTA
  } else if (pin == BUTTON_DFU_OTA) {
    secondary_reads++;
    pressed = second_held;
#endif
  } else {
    abort();
  }
  return BUTTON_PULL == NRF_GPIO_PIN_PULLDOWN ? pressed : !pressed;
}
static void delay_ms(uint32_t milliseconds) { now_ms += milliseconds; }
#define NRFX_DELAY_MS(x) delay_ms(x)
static bool bootloader_app_is_valid(void) { return true; }
static void disable_softdevice(void) { _sd_inited = false; }
static void mbr_init_sd(void) {}
static void led_state(int state) { (void)state; }
static void usb_init(bool cdc_only) { (void)cdc_only; usb_calls++; }
static void usb_teardown(void) {}
bool usb_wait_for_mount(uint32_t timeout_ms) {
  if (timeout_ms != DFU_USB_ENUMERATION_TIMEOUT_MS) abort();
  return host_mounts;
}
static void ble_stack_init(void) { ble_calls++; }
static void bootloader_dfu_start(bool ota, uint32_t timeout, bool cancel) {
  dfu_calls++; last_ota = ota; last_timeout = timeout; last_cancel = cancel;
}
'''
        harness += constants + "\n"
        harness += function(boards, "bool button_pressed(uint32_t pin)") + "\n"
        harness += function(main, "static void check_dfu_mode(void) {") + "\n"
        harness += r'''
int main(int argc, char **argv) {
  if (argc != 8) return 2;
  held_until = strtoul(argv[1], NULL, 0);
  power.GPREGRET = strtoul(argv[2], NULL, 0);
  host_mounts = atoi(argv[3]);
  release_after_qualification = atoi(argv[4]);
  single_tap = atoi(argv[5]);
  second_held = atoi(argv[7]);
  if (atoi(argv[6])) {
    dbl_reset_word = DFU_DBL_RESET_MAGIC;
    power.RESETREAS = POWER_RESETREAS_RESETPIN_Msk;
  }
  check_dfu_mode();
  printf("{\"elapsed_ms\":%u,\"usb_calls\":%u,\"ble_calls\":%u,"
         "\"dfu_calls\":%u,\"ota\":%u,\"timeout_ms\":%u,\"cancel\":%u,"
         "\"gpio_reads\":%u,\"pull\":%u,\"button\":%u,"
         "\"primary_reads\":%u,\"secondary_reads\":%u}\n",
         now_ms, usb_calls, ble_calls, dfu_calls, last_ota, last_timeout,
         last_cancel, gpio_reads, BUTTON_PULL, BUTTON_DFU,
         primary_reads, secondary_reads);
  return 0;
}
'''
        for board in ("t1000_e", "pca10056", "wismesh_tag"):
            binary = Path(cls.temp.name) / board
            flags = ["-DREQUIRE_SINGLE_BUTTON=1"] if board == "t1000_e" else []
            subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                            *flags, f'-DBOARD_HEADER="boards/{board}/board.h"',
                            "-x", "c", "-", "-I", str(ROOT / "src"),
                            "-o", str(binary)], input=harness, text=True,
                           check=True, capture_output=True)
            cls.binaries[board] = binary

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_entry(self, held_ms=0, magic=0, host=True, release=False,
                  single_tap=False, double_reset=False, second_held=False,
                  board="t1000_e"):
        output = subprocess.check_output([str(self.binaries[board]), str(held_ms), str(magic),
                                          str(int(host)), str(int(release)),
                                          str(int(single_tap)), str(int(double_reset)),
                                          str(int(second_held))])
        return json.loads(output)

    def test_electrical_contract_and_idle_boot(self):
        state = self.run_entry()
        self.assertEqual((state["button"], state["pull"]), (6, 1))
        self.assertEqual((state["elapsed_ms"], state["dfu_calls"]), (0, 0))

    def test_short_wake_press_stays_with_application(self):
        for duration in (1, 100, 1500, 2990, 3000):
            with self.subTest(duration=duration):
                state = self.run_entry(duration)
                self.assertEqual(state["dfu_calls"], 0)
                self.assertLessEqual(state["elapsed_ms"], 3000)

    def test_qualified_hold_uses_usb_with_host(self):
        state = self.run_entry(10000)
        self.assertEqual((state["elapsed_ms"], state["dfu_calls"], state["usb_calls"],
                          state["ble_calls"], state["ota"], state["cancel"]),
                         (3000, 1, 1, 0, 0, 1))

    def test_release_after_hold_does_not_change_transport(self):
        state = self.run_entry(3001, release=True)
        self.assertEqual((state["usb_calls"], state["ble_calls"], state["ota"]), (1, 0, 0))

    def test_no_host_retains_existing_ble_recovery(self):
        state = self.run_entry(10000, host=False)
        self.assertEqual((state["usb_calls"], state["ble_calls"], state["ota"]), (1, 1, 1))

    def test_explicit_usb_requests_and_double_reset_win(self):
        for magic in (0x4e, 0x57):
            with self.subTest(magic=magic):
                state = self.run_entry(10000, magic=magic)
                self.assertEqual((state["usb_calls"], state["ble_calls"], state["ota"],
                                  state["timeout_ms"]), (1, 0, 0, 30000))
                self.assertEqual((state["elapsed_ms"], state["gpio_reads"]), (0, 0))
        state = self.run_entry(10000, double_reset=True)
        self.assertEqual((state["usb_calls"], state["ble_calls"], state["ota"]), (1, 0, 0))
        self.assertEqual((state["elapsed_ms"], state["gpio_reads"]), (0, 0))

    def test_explicit_ble_request_wins(self):
        state = self.run_entry(10000, magic=0xa8)
        self.assertEqual((state["usb_calls"], state["ble_calls"], state["ota"]), (0, 1, 1))
        self.assertEqual((state["elapsed_ms"], state["gpio_reads"]), (0, 0))

    def test_explicit_skip_does_not_qualify_physical_hold(self):
        state = self.run_entry(10000, magic=0x6d)
        self.assertEqual((state["elapsed_ms"], state["gpio_reads"], state["dfu_calls"]),
                         (0, 0, 0))

    def test_non_opt_in_two_button_behavior_is_preserved(self):
        # Ordinary boot retains both original primary-button observations.
        idle = self.run_entry(board="pca10056")
        self.assertEqual((idle["primary_reads"], idle["secondary_reads"],
                          idle["dfu_calls"]), (2, 0, 0))
        # Explicit BLE preserves both original short circuits: no GPIO read.
        ble = self.run_entry(10000, magic=0xa8, second_held=True, board="pca10056")
        self.assertEqual((ble["gpio_reads"], ble["elapsed_ms"], ble["ota"]), (0, 0, 1))
        # With explicit USB, the original two-button override still samples
        # both physical controls and requests BLE when both are held.
        both = self.run_entry(10000, magic=0x57, second_held=True, board="pca10056")
        self.assertEqual((both["primary_reads"], both["secondary_reads"],
                          both["ota"]), (1, 1, 1))
        one = self.run_entry(10000, magic=0x57, board="pca10056")
        self.assertEqual((one["primary_reads"], one["secondary_reads"],
                          one["ota"]), (1, 1, 0))

    def test_non_opt_in_wismesh_wake_delay_is_preserved(self):
        state = self.run_entry(10000, magic=0x57, board="wismesh_tag")
        self.assertEqual((state["elapsed_ms"], state["ota"]), (500, 1))

    def test_held_button_overrides_brief_makecode_timeout(self):
        state = self.run_entry(10000, single_tap=True)
        self.assertEqual((state["usb_calls"], state["ota"], state["timeout_ms"]), (1, 0, 0))


if __name__ == "__main__":
    unittest.main()
