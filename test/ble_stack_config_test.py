#!/usr/bin/env python3
"""Compare every byte/order/error policy of the shared builder with SDK fields."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BleStackConfig(unittest.TestCase):
    def test_real_sdk_configurations_and_error_policy(self):
        code = r'''
#include <assert.h>
#include <setjmp.h>
#include <stdint.h>
#include <string.h>
#include "ble.h"
#define BLEGATT_ATT_MTU_MAX TEST_MTU
#define BLE_CONN_CFG_HIGH_BANDWIDTH TEST_TAG
#define BLEGAP_EVENT_LENGTH 24
#define BLEGATTS_HVN_QSIZE 8
#define BLEGATTC_WRCMD_QSIZE 3
static jmp_buf reset;
static unsigned count, checks, fail_at;
static uint32_t fault;
static ble_cfg_t values[7];
static const uint16_t ids[] = {BLE_GAP_CFG_ROLE_COUNT, BLE_GATTS_CFG_SERVICE_CHANGED,
  BLE_COMMON_CFG_VS_UUID, BLE_CONN_CFG_GATT, BLE_CONN_CFG_GAP,
  BLE_CONN_CFG_GATTS, BLE_CONN_CFG_GATTC};
#define APP_ERROR_CHECK(value) do { uint32_t checked_error = (value); ++checks; \
  if (checked_error) { fault = checked_error; longjmp(reset, 1); } } while (0)
#include "dfu_ble_config.h"
uint32_t sd_ble_cfg_set(uint32_t id, const ble_cfg_t *config, uint32_t ram) {
  assert(count < 7 && id == ids[count] && ram == 0x20006400);
  memcpy(&values[count], config, sizeof(*config));
  return ++count == fail_at ? 0x9876 : 0;
}
static void golden(unsigned index, ble_cfg_t *config) {
  memset(config, 0, sizeof(*config));
  if (index >= 3) config->conn_cfg.conn_cfg_tag = TEST_TAG;
  switch (index) {
    case 0: config->gap_cfg.role_count_cfg.adv_set_count = 1;
            config->gap_cfg.role_count_cfg.periph_role_count = 1; break;
    case 1: config->gatts_cfg.service_changed.service_changed = 1; break;
    case 2: config->common_cfg.vs_uuid_cfg.vs_uuid_count = 2; break;
    case 3: config->conn_cfg.params.gatt_conn_cfg.att_mtu = TEST_MTU; break;
    case 4: config->conn_cfg.params.gap_conn_cfg.conn_count = 1;
            config->conn_cfg.params.gap_conn_cfg.event_length = 24; break;
    case 5: config->conn_cfg.params.gatts_conn_cfg.hvn_tx_queue_size = 8; break;
    case 6: config->conn_cfg.params.gattc_conn_cfg.write_cmd_tx_queue_size = 3; break;
    default: assert(0);
  }
}
int main(void) {
  for (fail_at = 0; fail_at <= 7; ++fail_at) {
    count = checks = fault = 0;
    if (setjmp(reset) == 0) dfu_ble_stack_configure(0x20006400);
    assert(count == (fail_at == 3 ? 3u : 7u));
    assert(checks == 1 && fault == (fail_at == 3 ? 0x9876u : 0u));
    for (unsigned i = 0; i < count; ++i) {
      ble_cfg_t expected;
      golden(i, &expected);
      assert(memcmp(&values[i], &expected, sizeof(expected)) == 0);
    }
  }
  return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='otafix-ble-config-') as directory:
            work = Path(directory)
            sanitizers = (['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
                          if os.environ.get('SECURE_DFU_TEST_SANITIZE') == '1' else [])
            for sdk in ('s140_nrf52_6.1.1', 's140_nrf52_7.3.0', 's132_nrf52_6.1.1'):
                headers = ROOT / 'lib/softdevice' / sdk / (sdk + '_API/include')
                for mtu, tag in ((23, 1), (247, 7)):
                    with self.subTest(sdk=sdk, mtu=mtu, tag=tag):
                        binary = work / (sdk + str(mtu) + ('.exe' if os.name == 'nt' else ''))
                        subprocess.run([os.environ.get('CC', 'gcc'), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            '-DSVCALL_AS_NORMAL_FUNCTION', '-DNRF52840_XXAA', '-D__STATIC_INLINE=static inline',
                            f'-DTEST_MTU={mtu}', f'-DTEST_TAG={tag}', *sanitizers,
                            '-I' + str(ROOT / 'src'), '-I' + str(headers), '-I' + str(headers / 'nrf52'),
                            '-I' + str(ROOT / 'lib/nrfx/mdk'), '-I' + str(ROOT / 'src/cmsis/include'),
                            '-x', 'c', '-', '-o', str(binary)], input=code, text=True, check=True)
                        subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
