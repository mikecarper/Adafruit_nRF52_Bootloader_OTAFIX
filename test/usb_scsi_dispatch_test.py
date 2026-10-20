#!/usr/bin/env python3
"""Execute the production non-built-in SCSI dispatcher against a sense mock."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UsbScsiDispatch(unittest.TestCase):
    def test_all_opcodes_lengths_and_luns_preserve_no_data_semantics(self):
        source = (ROOT / 'src/usb/msc_uf2.c').read_text()
        start = source.index('int32_t tud_msc_scsi_cb (')
        function = source[start:source.index('\n}', start) + 2]
        code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#define SCSI_CMD_PREVENT_ALLOW_MEDIUM_REMOVAL 0x1e
#define SCSI_SENSE_ILLEGAL_REQUEST 5
static unsigned calls;
static uint8_t expected_lun;
static bool tud_msc_set_sense(uint8_t lun, uint8_t key, uint8_t asc, uint8_t ascq) {
  assert(lun == expected_lun && key == 5 && asc == 0x20 && ascq == 0);
  ++calls;
  return true;
}
''' + function + r'''
int main(void) {
  uint8_t guarded[64];
  const uint16_t sizes[] = {0, 1, 512, UINT16_MAX};
  const uint8_t luns[] = {0, 3, UINT8_MAX};
  for (unsigned op = 0; op < 256; ++op) {
    uint8_t command[16] = {(uint8_t)op};
    for (unsigned lun = 0; lun < sizeof(luns); ++lun) {
      expected_lun = luns[lun];
      for (unsigned size = 0; size < sizeof(sizes) / sizeof(sizes[0]); ++size) {
        memset(guarded, 0xa5, sizeof(guarded));
        calls = 0;
        bool supported = op == 0x1e || op == 0x35;
        int32_t result = tud_msc_scsi_cb(expected_lun, command, guarded + 16, sizes[size]);
        assert(result == (supported ? 0 : -1));
        assert(calls == !supported);
        for (unsigned i = 0; i < sizeof(guarded); ++i) assert(guarded[i] == 0xa5);
      }
    }
  }
  return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='otafix-scsi-dispatch-') as directory:
            binary = Path(directory) / ('dispatch.exe' if os.name == 'nt' else 'dispatch')
            sanitizers = (['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
                          if os.environ.get('SECURE_DFU_TEST_SANITIZE') == '1' else [])
            subprocess.run([os.environ.get('CC', 'gcc'), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            *sanitizers, '-x', 'c', '-', '-o', str(binary)], input=code, text=True, check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
