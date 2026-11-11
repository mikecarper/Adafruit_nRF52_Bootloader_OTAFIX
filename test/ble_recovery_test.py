#!/usr/bin/env python3
"""Execute production BLE recovery hints and their settings-commit boundary."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "lib/sdk11/components/libraries/bootloader_dfu"


def function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"unterminated production function: {signature}")


def declaration(source, name):
    end = source.index(name) + len(name)
    return source[source.rfind("typedef ", 0, end):end]


class BleRecoveryTest(unittest.TestCase):
    def test_forced_ble_restart_cannot_apply_a_previous_lora_handoff(self):
        source = (ROOT / "src/main.c").read_text()
        gate = re.search(r"if\s*\(\s*!bootloader_must_be_reentered\s*&&\s*ota_delta_check_and_apply\(\)",
                         source)
        self.assertIsNotNone(gate, "forced recovery must bypass application-driven apply")
        harness = r'''
#include <assert.h>
#include <stdbool.h>
static unsigned applies, resets;
static bool apply_success;
static bool ota_delta_check_and_apply(void) { ++applies; return apply_success; }
static void otafix_system_reset(void) { ++resets; }
static void handoff(bool bootloader_must_be_reentered) {
'''
        harness += function(source, gate.group(0)) + "}\n"
        harness += r'''
int main(void) {
  for (unsigned force = 0; force != 2; ++force) {
    for (unsigned success = 0; success != 2; ++success) {
      applies = resets = 0; apply_success = success != 0;
      handoff(force != 0);
      assert(applies == (unsigned)!force);
      assert(resets == (unsigned)(!force && success));
    }
  }
  return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="otafix-ble-apply-gate-") as directory:
            binary = Path(directory) / ("gate.exe" if os.name == "nt" else "gate")
            subprocess.run([os.environ.get("CC", "gcc"), "-std=c11", "-O2", "-Wall", "-Wextra",
                            "-Werror", "-x", "c", "-", "-o", str(binary)],
                           input=harness, text=True, check=True)
            subprocess.run([str(binary)], check=True)

    def test_main_rearms_invalid_ble_entry_and_releases_valid_application(self):
        source = (ROOT / "src/main.c").read_text()
        rearm = "if (!valid_app && NRF_POWER->GPREGRET == 0)"
        release = "if (NRF_POWER->GPREGRET == DFU_MAGIC_OTA_RESET)"
        entry_at = source.index(rearm)
        self.assertLess(entry_at, source.index("ble_stack_init();", entry_at))
        release_at = source.index(release)
        self.assertLess(release_at, source.index("bootloader_app_start();"))
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include "dfu_entry.h"
static struct { uint32_t GPREGRET, GPREGRET2; } power;
#define NRF_POWER (&power)
static void enter_ble(bool valid_app) {
'''
        harness += function(source, rearm) + "}\nstatic void enter_app(void) {\n"
        harness += function(source, release) + "}\n"
        harness += r'''
int main(void) {
  const uint32_t magics[] = {0, DFU_MAGIC_OTA_RESET, 0x4E, 0x57, 0x6D, 0xD1, 0xFF};
  for (unsigned valid = 0; valid != 2; ++valid) {
    for (unsigned i = 0; i != sizeof(magics) / sizeof(magics[0]); ++i) {
      power.GPREGRET = magics[i]; power.GPREGRET2 = 0xD5;
      enter_ble(valid != 0);
      assert(power.GPREGRET == (!valid && magics[i] == 0 ? DFU_MAGIC_OTA_RESET : magics[i]));
      assert(power.GPREGRET2 == 0xD5);
      enter_app();
      assert(power.GPREGRET == ((!valid && magics[i] == 0) || magics[i] == DFU_MAGIC_OTA_RESET ? 0 : magics[i]));
      assert(power.GPREGRET2 == 0xD5);
    }
  }
  /* Pin/watchdog re-entry repeatedly consumes and re-arms the same owned hint. */
  for (unsigned restart = 0; restart != 4; ++restart) {
    power.GPREGRET = 0;
    enter_ble(false);
    assert(dfu_entry_reset_magic(power.GPREGRET) == DFU_MAGIC_OTA_RESET);
    assert(dfu_entry_single_button_route(true, false, true, false) == DFU_SINGLE_BUTTON_BLE);
  }
  return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="otafix-ble-entry-") as directory:
            binary = Path(directory) / ("entry.exe" if os.name == "nt" else "entry")
            subprocess.run([os.environ.get("CC", "gcc"), "-std=c11", "-O2", "-Wall", "-Wextra",
                            "-Werror", "-I" + str(ROOT / "src"), "-x", "c", "-", "-o", str(binary)],
                           input=harness, text=True, check=True)
            subprocess.run([str(binary)], check=True)

    def test_hint_is_owned_by_ble_and_cleared_only_after_settings_commit(self):
        source = (CORE / "bootloader.c").read_text()
        types = (CORE / "dfu_types.h").read_text()
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <setjmp.h>
#include "bootloader_types.h"
#include "dfu_entry.h"
#define NRF_SUCCESS 0u
#define PSTORAGE_STORE_OP_CODE 1u
#define PSTORAGE_CLEAR_OP_CODE 2u
static jmp_buf fatal;
static uint32_t fatal_code;
#define APP_ERROR_CHECK(value) do { uint32_t code_ = (value); \
  if (code_ != NRF_SUCCESS) { fatal_code = code_; longjmp(fatal, 1); } } while (0)
typedef struct { uint32_t block_id; } pstorage_handle_t;
static struct { uint32_t GPREGRET, GPREGRET2; } power;
#define NRF_POWER (&power)
static bool ota, settings_integrity = true;
static unsigned gets, sets, clears, saves;
static uint32_t get_error, set_error, clear_error;
static bool is_ota(void) { return ota; }
static uint32_t sd_power_gpregret_get(uint32_t index, uint32_t *value) {
  assert(index == 0); ++gets;
  if (get_error == 0) *value = power.GPREGRET;
  return get_error;
}
static uint32_t sd_power_gpregret_set(uint32_t index, uint32_t value) {
  assert(index == 0 && value == DFU_MAGIC_OTA_RESET); ++sets;
  if (set_error == 0) power.GPREGRET |= value;
  return set_error;
}
static uint32_t sd_power_gpregret_clr(uint32_t index, uint32_t value) {
  assert(index == 0 && value == DFU_MAGIC_OTA_RESET); ++clears;
  if (clear_error == 0) power.GPREGRET &= ~value;
  return clear_error;
}
static bootloader_settings_t before, saved;
static void bootloader_util_settings_get(bootloader_settings_t const **settings) {
  *settings = &before;
}
static bool bootloader_settings_integrity_valid(bootloader_settings_t const *settings) {
  assert(settings == &before); return settings_integrity;
}
static uint32_t dfu_transport_ble_close(void) { return NRF_SUCCESS; }
static uint32_t dfu_transport_serial_close(void) { return NRF_SUCCESS; }
'''
        harness += declaration(source, "bootloader_status_t;")
        harness += declaration(types, "dfu_update_status_code_t;")
        harness += declaration(types, "dfu_update_status_t;")
        harness += r'''
static bootloader_status_t m_update_status;
static uint8_t m_settings_store_pending;
static void bootloader_settings_save(bootloader_settings_t *settings) {
  saved = *settings; ++saves;
  m_settings_store_pending = 2;
}
'''
        for signature in (
            "static void bootloader_ble_recovery_hint(bool retain)",
            "static void pstorage_callback_handler(",
            "void bootloader_dfu_restart(void)",
            "void bootloader_dfu_update_process(",
            "bool bootloader_dfu_app_update_complete(void)",
        ):
            harness += function(source, signature) + "\n"
        harness += r'''
static void reset_case(bool use_ota, uint32_t magic) {
  ota = use_ota; power.GPREGRET = magic; power.GPREGRET2 = 0xD5;
  settings_integrity = true;
  gets = sets = clears = saves = 0;
  get_error = set_error = clear_error = fatal_code = 0;
  m_update_status = BOOTLOADER_UPDATING;
  m_settings_store_pending = 0;
  before = (bootloader_settings_t){.bank_0 = BANK_VALID_APP, .bank_0_crc = 0x1234,
    .bank_1 = BANK_INVALID_APP, .bank_0_size = 512};
}
static void callback(unsigned operation) {
  pstorage_callback_handler(NULL, operation, NRF_SUCCESS, NULL, 0);
}
int main(void) {
  const uint32_t magics[] = {0, DFU_MAGIC_OTA_RESET, 0x4E, 0x57, 0x6D, 0xD1, 0xFF};
  for (unsigned use_ota = 0; use_ota != 2; ++use_ota) {
    for (unsigned i = 0; i != sizeof(magics) / sizeof(magics[0]); ++i) {
      reset_case(use_ota != 0, magics[i]);
      bootloader_dfu_update_process(&(dfu_update_status_t){.status_code = DFU_BANK_0_ERASED});
      const uint32_t expected = ota && magics[i] == 0 ? DFU_MAGIC_OTA_RESET : magics[i];
      assert(power.GPREGRET == expected && power.GPREGRET2 == 0xD5);
      assert(saves == 1 && saved.bank_0 == BANK_INVALID_APP);
      assert(saved.bank_0_size == 0 && saved.bank_0_crc == 0);
      assert(ota ? gets == 1 : gets == 0);
      assert(sets == (unsigned)(ota && magics[i] == 0));
      /* Completing invalidation is not a successful firmware update. */
      callback(PSTORAGE_STORE_OP_CODE); callback(PSTORAGE_STORE_OP_CODE);
      assert(power.GPREGRET == expected && clears == 0);
    }
  }
  const unsigned complete[] = {DFU_UPDATE_APP_COMPLETE, DFU_UPDATE_SD_COMPLETE,
                               DFU_UPDATE_BOOT_COMPLETE, DFU_UPDATE_SD_SWAPPED};
  for (unsigned use_ota = 0; use_ota != 2; ++use_ota) {
    for (unsigned mode = 0; mode != sizeof(complete) / sizeof(complete[0]); ++mode) {
      for (unsigned i = 0; i != sizeof(magics) / sizeof(magics[0]); ++i) {
        reset_case(use_ota != 0, magics[i]);
        bootloader_dfu_update_process(&(dfu_update_status_t){.status_code = complete[mode],
          .app_crc = 0x4321, .app_size = 256, .sd_size = 128, .bl_size = 64});
        const bool app_update = complete[mode] == DFU_UPDATE_APP_COMPLETE;
        const bootloader_status_t saving = app_update ? BOOTLOADER_APP_SETTINGS_SAVING
                                                     : BOOTLOADER_SETTINGS_SAVING;
        assert(m_update_status == saving && saves == 1);
        assert(!bootloader_dfu_app_update_complete());
        if (complete[mode] == DFU_UPDATE_APP_COMPLETE) {
          assert(saved.bank_0 == BANK_VALID_APP && saved.bank_0_crc == 0x4321);
          assert(saved.bank_0_size == 256 && saved.bank_1 == BANK_INVALID_APP);
          assert(saved.sd_image_size == 0 && saved.bl_image_size == 0 && saved.app_image_size == 0);
        } else if (complete[mode] == DFU_UPDATE_SD_COMPLETE) {
          assert(saved.bank_0 == BANK_VALID_SD && saved.bank_0_crc == 0x4321);
          assert(saved.bank_0_size == 448 && saved.bank_1 == BANK_INVALID_APP);
          assert(saved.sd_image_size == 128 && saved.bl_image_size == 64 && saved.app_image_size == 256);
        }
        /* Neither erase completion nor the first settings fragment may release the hint. */
        callback(PSTORAGE_CLEAR_OP_CODE);
        assert(m_settings_store_pending == 2 && power.GPREGRET == magics[i]);
        assert(m_update_status == saving && !bootloader_dfu_app_update_complete());
        callback(PSTORAGE_STORE_OP_CODE);
        assert(m_settings_store_pending == 1 && power.GPREGRET == magics[i]);
        assert(m_update_status == saving && !bootloader_dfu_app_update_complete());
        callback(PSTORAGE_STORE_OP_CODE);
        assert(m_update_status == (app_update ? BOOTLOADER_APP_COMPLETE : BOOTLOADER_COMPLETE));
        assert(bootloader_dfu_app_update_complete() == app_update);
        assert(power.GPREGRET == (ota && magics[i] == DFU_MAGIC_OTA_RESET ? 0 : magics[i]));
        assert(power.GPREGRET2 == 0xD5);
        assert(clears == (unsigned)(ota && magics[i] == DFU_MAGIC_OTA_RESET));
        /* A repeated completion callback cannot clear a later unrelated request. */
        power.GPREGRET = 0xD1;
        callback(PSTORAGE_STORE_OP_CODE);
        assert(power.GPREGRET == 0xD1);
      }
    }
  }
  /* BOOT preserves the prior sealed application, while SWAPPED invalidates an SD staging bank. */
  const unsigned prior_banks[] = {BANK_VALID_APP, BANK_VALID_SD, BANK_INVALID_APP, BANK_ERASED};
  for (unsigned swapped = 0; swapped != 2; ++swapped) {
    for (unsigned integrity = 0; integrity != 2; ++integrity) {
      for (unsigned bank = 0; bank != sizeof(prior_banks) / sizeof(prior_banks[0]); ++bank) {
        reset_case(true, DFU_MAGIC_OTA_RESET);
        settings_integrity = integrity != 0;
        before.bank_0 = prior_banks[bank];
        bootloader_dfu_update_process(&(dfu_update_status_t){
          .status_code = swapped ? DFU_UPDATE_SD_SWAPPED : DFU_UPDATE_BOOT_COMPLETE,
          .sd_size = 128, .bl_size = 64, .app_size = 256, .sd_image_start = 4096});
        const bool preserves = integrity && !(swapped && before.bank_0 == BANK_VALID_SD);
        assert(saved.bank_0 == (preserves ? before.bank_0 : BANK_INVALID_APP));
        assert(saved.bank_0_crc == (preserves ? before.bank_0_crc : 0));
        assert(saved.bank_0_size == (preserves ? before.bank_0_size : 0));
        assert(saved.bank_1 == (swapped ? BANK_INVALID_APP : BANK_VALID_BOOT));
        assert(saved.sd_image_size == (swapped ? 0 : 128));
        assert(saved.bl_image_size == (swapped ? 0 : 64));
        assert(saved.app_image_size == (swapped ? 0 : 256));
        assert(saved.sd_image_start == 0 && power.GPREGRET == DFU_MAGIC_OTA_RESET);
        callback(PSTORAGE_STORE_OP_CODE); callback(PSTORAGE_STORE_OP_CODE);
        assert(m_update_status == BOOTLOADER_COMPLETE && power.GPREGRET == 0);
      }
    }
  }
  /* A recovery reset stays authoritative while older scheduled work drains. */
  for (unsigned route = 0; route != 8; ++route) {
    const bool direct = (route & 2U) != 0;
    const bool use_ota = (route & 1U) != 0;
    for (unsigned i = 0; i != sizeof(magics) / sizeof(magics[0]); ++i) {
      reset_case(use_ota != 0, magics[i]);
      m_update_status = route & 4U ? BOOTLOADER_APP_SETTINGS_SAVING : BOOTLOADER_SETTINGS_SAVING;
      m_settings_store_pending = 2;
      if (direct) {
        bootloader_dfu_restart();
      } else {
        bootloader_dfu_update_process(&(dfu_update_status_t){.status_code = DFU_RESET,
                                                           .restart_into_bootloader = true});
      }
      const uint32_t expected = ota && magics[i] == 0 ? DFU_MAGIC_OTA_RESET : magics[i];
      assert(m_update_status == BOOTLOADER_RESET_TO_SELF && power.GPREGRET == expected);
      assert(!bootloader_dfu_app_update_complete());
      const unsigned prior_gets = gets;
      callback(PSTORAGE_STORE_OP_CODE); callback(PSTORAGE_STORE_OP_CODE);
      assert(m_settings_store_pending == 2 && m_update_status == BOOTLOADER_RESET_TO_SELF);
      const unsigned late[] = {DFU_TIMEOUT, DFU_BANK_0_ERASED, DFU_UPDATE_APP_COMPLETE,
        DFU_UPDATE_SD_COMPLETE, DFU_UPDATE_BOOT_COMPLETE, DFU_UPDATE_SD_SWAPPED, DFU_RESET};
      for (unsigned event = 0; event != sizeof(late) / sizeof(late[0]); ++event) {
        bootloader_dfu_update_process(&(dfu_update_status_t){.status_code = late[event]});
        assert(m_update_status == BOOTLOADER_RESET_TO_SELF);
        assert(power.GPREGRET == expected && power.GPREGRET2 == 0xD5);
        assert(gets == prior_gets && clears == 0 && saves == 0);
      }
    }
  }
  /* A normal valid-application cancel does not become sticky BLE recovery. */
  reset_case(true, 0);
  bootloader_dfu_update_process(&(dfu_update_status_t){.status_code = DFU_RESET});
  assert(m_update_status == BOOTLOADER_SYS_RESET && power.GPREGRET == 0 && gets == 0);
  /* A failed SD register operation follows the production fatal path, never settings writes. */
  for (unsigned operation = 0; operation != 3; ++operation) {
    reset_case(true, operation == 2 ? DFU_MAGIC_OTA_RESET : 0);
    if (operation == 0) get_error = 17;
    if (operation == 1) set_error = 18;
    if (operation == 2) clear_error = 19;
    if (setjmp(fatal) == 0) {
      bootloader_ble_recovery_hint(operation != 2);
      assert(!"failed SoftDevice request must not be ignored");
    }
    assert(fatal_code == 17 + operation && saves == 0);
    assert(power.GPREGRET2 == 0xD5);
  }
  return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="otafix-ble-recovery-") as directory:
            binary = Path(directory) / ("recovery.exe" if os.name == "nt" else "recovery")
            subprocess.run([os.environ.get("CC", "gcc"), "-std=c11", "-O2", "-Wall", "-Wextra",
                            "-Werror", "-Wno-unused-parameter", "-I" + str(CORE),
                            "-I" + str(ROOT / "src"), "-x", "c", "-", "-o", str(binary)],
                           input=harness, text=True, check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
