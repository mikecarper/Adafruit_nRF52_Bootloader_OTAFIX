#!/usr/bin/env python3
"""Run real MSC eject callbacks across status, reset, and update boundaries."""

from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def function(source, signature):
    start = source.index(signature)
    return source[start:source.index("\n}", start) + 2]


class Uf2EjectTests(unittest.TestCase):
    def test_real_read_callback_initializes_only_complete_sectors(self):
        source = (ROOT / "src/usb/msc_uf2.c").read_text()
        harness = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#define TU_ASSERT(condition, result) do { if (!(condition)) return (result); } while (0)
static unsigned reads;
static uint32_t expected_lba;
static void read_block(uint32_t lba, uint8_t *data) {
  assert(lba == expected_lba++);
  memset(data, 0, 512);
  data[0] = (uint8_t)lba;
  data[511] = 0x5a;
  reads++;
}
'''
        harness += function(source, "int32_t tud_msc_read10_cb (")
        harness += r'''
int main(void) {
  uint8_t guarded[16 + 3 * 512 + 16];
  memset(guarded, 0xa5, sizeof(guarded));
  expected_lba = 17;
  assert(tud_msc_read10_cb(0, 17, 0, guarded + 16, 3 * 512) == 3 * 512);
  assert(reads == 3 && expected_lba == 20);
  for (unsigned i = 0; i < 16; i++) {
    assert(guarded[i] == 0xa5 && guarded[sizeof(guarded) - 1 - i] == 0xa5);
  }
  for (unsigned sector = 0; sector < 3; sector++) {
    uint8_t *data = guarded + 16 + sector * 512;
    assert(data[0] == 17 + sector && data[511] == 0x5a);
    for (unsigned i = 1; i < 511; i++) assert(data[i] == 0);
  }
  memset(guarded, 0xa5, sizeof(guarded));
  reads = 0;
  assert(tud_msc_read10_cb(0, 17, 1, guarded + 16, 512) == -1);
  uint32_t const partial_sizes[] = {1, 511, 513, 1025};
  for (unsigned i = 0; i < sizeof(partial_sizes) / sizeof(partial_sizes[0]); i++) {
    assert(tud_msc_read10_cb(0, 17, 0, guarded + 16, partial_sizes[i]) == -1);
  }
  assert(tud_msc_read10_cb(0, 17, 0, guarded + 16, 0) == 0 && reads == 0);
  for (unsigned i = 0; i < sizeof(guarded); i++) assert(guarded[i] == 0xa5);
  return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "msc-read"
            subprocess.run(
                ["cc", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror",
                 "-x", "c", "-", "-o", str(binary)],
                input=harness, text=True, check=True, capture_output=True,
            )
            subprocess.run([str(binary)], check=True)

    def test_real_callbacks_with_and_without_board_opt_in(self):
        source = (ROOT / "src/usb/msc_uf2.c").read_text()
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include BOARD_HEADER
#include "usb/uf2/uf2_transfer_state.h"
typedef struct { uint8_t updateKind; bool aborted, appValidated; } WriteState;
enum { UF2_UPDATE_KIND_BOOTLOADER = 2, DFU_RESET = 4,
       SCSI_CMD_START_STOP_UNIT = 0x1b };
typedef struct { int status_code; bool restart_into_bootloader; } dfu_update_status_t;
static unsigned exits, completions, discards;
static void flash_nrf5x_discard(void) { discards++; }
static uint32_t app_timer_cnt_get(void) { return 1234; }
#ifdef UF2_EXIT_ON_EJECT
static void bootloader_dfu_update_process(dfu_update_status_t status) {
  assert(status.status_code == DFU_RESET && !status.restart_into_bootloader);
  exits++;
}
#endif
'''
        harness += source[source.index("static WriteState _wr_state"):
                          source.index("#define UF2_APP_COMPLETION_IDLE_MS")]
        harness += r'''
static void complete_app_update(void) {
  assert(_wr_state.appValidated && !_wr_state.aborted);
  completions++;
}
'''
        for signature in (
            "static bool take_pending_app_completion(void)",
            "void uf2_write_session_reset(void)",
            "__attribute__((noinline)) static void finish_msc_command(void)",
            "void tud_msc_command_complete_cb(uint8_t lun, uint8_t const scsi_cmd[16])",
            "void tud_msc_reset_cb(void)",
            "void tud_msc_scsi_complete_cb(uint8_t lun, uint8_t const scsi_cmd[16])",
            "bool tud_msc_start_stop_cb(uint8_t lun, uint8_t power_condition, bool start, bool load_eject)",
        ):
            harness += function(source, signature) + "\n"
        harness += r'''
static uint8_t const eject[16] = {SCSI_CMD_START_STOP_UNIT};
static uint8_t const sync_cache[16] = {0x35};
static void reset_state(void) {
  uf2_write_session_reset();
  exits = completions = discards = 0;
}
int main(void) {
#ifdef UF2_EXIT_ON_EJECT
  unsigned const expected_exits = 1;
#else
  unsigned const expected_exits = 0;
#endif
  reset_state();
  _wr_state.appValidated = true;
  _app_completion_pending = true;
  _app_msc_command_active = true;
  _app_completion_last_activity = 0;
  tud_msc_command_complete_cb(0, sync_cache);
  assert(!_app_msc_command_active && _app_completion_pending);
  assert(_app_completion_last_activity == 1234 && completions == 0);
  _app_msc_command_active = true;
  _app_completion_last_activity = 0;
  tud_msc_reset_cb();
  assert(!_app_msc_command_active && _app_completion_pending);
  assert(_app_completion_last_activity == 1234 && completions == 0);

  reset_state();
  assert(tud_msc_start_stop_cb(0, 0, false, true));
  assert(exits == 0); // Acceptance alone cannot detach before the status.
  tud_msc_scsi_complete_cb(0, sync_cache);
  assert(exits == 0);
  tud_msc_scsi_complete_cb(0, eject);
  assert(exits == expected_exits && completions == 0);
  tud_msc_scsi_complete_cb(0, eject);
  assert(exits == expected_exits); // Duplicate completion cannot exit twice.

  reset_state();
  tud_msc_start_stop_cb(0, 0, false, true);
  tud_msc_reset_cb(); // A cancelled BOT/bus eject is not permission to exit.
  tud_msc_scsi_complete_cb(0, eject);
  assert(exits == 0 && completions == 0);

  reset_state();
  tud_msc_start_stop_cb(0, 0, false, true);
  // Failed CSWs invoke only generic completion. A later successful load must
  // not reuse the failed command's permission to leave recovery.
  tud_msc_command_complete_cb(0, eject);
  tud_msc_start_stop_cb(0, 0, true, true);
  tud_msc_scsi_complete_cb(0, eject);
  assert(exits == 0 && completions == 0);

  reset_state();
  tud_msc_start_stop_cb(0, 0, false, true);
  uf2_write_session_reset();
  tud_msc_scsi_complete_cb(0, eject);
  assert(exits == 0);

  reset_state();
  tud_msc_start_stop_cb(0, 0, true, true); // Loading media is not ejecting.
  tud_msc_scsi_complete_cb(0, eject);
  tud_msc_start_stop_cb(0, 0, false, false); // Stop without LOEJ is not ejecting.
  tud_msc_scsi_complete_cb(0, eject);
  assert(exits == 0 && completions == 0);

  reset_state();
  _wr_state.appValidated = true;
  _app_completion_pending = true;
  tud_msc_start_stop_cb(0, 0, false, true);
  assert(exits == 0 && completions == 0 && _app_completion_pending);
  tud_msc_scsi_complete_cb(0, eject);
  assert(exits == 0 && completions == 1 && !_app_completion_pending);
  tud_msc_scsi_complete_cb(0, eject);
  assert(completions == 1); // Completed image retains its settings-save path.

  reset_state();
  _wr_state.appValidated = true;
  _app_completion_pending = true;
  tud_msc_start_stop_cb(0, 0, false, true);
  tud_msc_command_complete_cb(0, eject); // Failed eject leaves image pending.
  tud_msc_start_stop_cb(0, 0, true, true);
  tud_msc_scsi_complete_cb(0, eject);
  assert(exits == 0 && completions == 0 && _app_completion_pending);

  reset_state();
  _wr_state.appValidated = true;
  _app_completion_pending = true;
  tud_msc_start_stop_cb(0, 0, false, true);
  tud_msc_reset_cb();
  tud_msc_scsi_complete_cb(0, eject);
  assert(exits == 0 && completions == 0 && _app_completion_pending);

  reset_state();
  _wr_state.aborted = true;
  _app_completion_pending = true;
  tud_msc_start_stop_cb(0, 0, false, true);
  tud_msc_scsi_complete_cb(0, eject);
  assert(exits == 0 && completions == 0); // Failed image is never blessed.

  reset_state();
  _wr_state.updateKind = UF2_UPDATE_KIND_BOOTLOADER;
  tud_msc_start_stop_cb(0, 0, false, true);
  tud_msc_scsi_complete_cb(0, eject);
  assert(discards == 1 && completions == 0 && exits == expected_exits);
  return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            for board in ("t1000_e", "pca10056"):
                with self.subTest(board=board):
                    binary = Path(directory) / board
                    subprocess.run(
                        ["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                         f'-DBOARD_HEADER="boards/{board}/board.h"',
                         "-x", "c", "-", "-I", str(ROOT / "src"), "-o", str(binary)],
                        input=harness, text=True, check=True, capture_output=True,
                    )
                    subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
