#!/usr/bin/env python3
"""Execute shared DFU builders with real Nordic ABI types and mock SVCs.

Extract production definitions without pulling unrelated device event code
into a host process. Attribute metadata, UUID/order, permissions and pointers
are checked field-for-field; notification bytes/guards/resource retries are
exercised under native ASan/UBSan. No ARM compiler or hardware is used.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "lib/sdk11/components/ble/ble_services/ble_dfu/ble_dfu.c"
FIXTURE = ROOT / "test/fixtures/ble_dfu_shared.c"


def definition(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    token = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]')
    for match in token.finditer(source, opening):
        if match[0] == "{":
            depth += 1
        elif match[0] == "}":
            depth -= 1
            if depth == 0:
                return source[start:match.end()]
    raise AssertionError("unterminated production definition: " + signature)


class BleDfuSharedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cc = os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc")
        if not cls.cc:
            raise unittest.SkipTest("a native C11 compiler is required")
        cls.temp = tempfile.TemporaryDirectory(prefix="ble-dfu-shared-")
        cls.work = Path(cls.temp.name)
        source = SOURCE.read_text(encoding="ascii")
        prefix = source[source.index("#define MAX_DFU_PKT_LEN"):source.index("// Preserve the three existing attributes")]
        signatures = ("static uint32_t dfu_characteristic_add(", "static uint32_t dfu_pkt_char_add(",
                      "static uint32_t dfu_rev_char_add(", "static uint32_t dfu_ctrl_pt_add(",
                      "uint32_t ble_dfu_init(", "static uint32_t dfu_notification_send(",
                      "uint32_t ble_dfu_bytes_rcvd_report(", "uint32_t ble_dfu_pkts_rcpt_notify(",
                      "uint32_t ble_dfu_response_send(", "static bool is_cccd_configured(",
                      "static uint32_t on_ctrl_pt_write(")
        methods = "\n".join(definition(source, signature) for signature in signatures)
        mapping_asserts = source[source.index("_Static_assert(BLE_DFU_START"):
                                 source.index("static uint32_t on_ctrl_pt_write(")]
        methods = mapping_asserts + "\n" + methods
        harness = FIXTURE.read_text().replace("@PRODUCTION@", prefix + "\n" + methods)
        (cls.work / "main.c").write_text(harness)
        # Only the common-service utility header is replaced. All public DFU,
        # GATT, GAP, UUID, attribute and HVX types come from the shipped SDK.
        (cls.work / "ble_srv_common.h").write_text('''#pragma once
#include <stdint.h>
#include <stdbool.h>
#define BLE_CCCD_VALUE_LEN 2
typedef void (*ble_srv_error_handler_t)(uint32_t);
static inline uint16_t uint16_decode(const uint8_t *in) { return in[0] | ((uint16_t)in[1] << 8); }
static inline bool ble_srv_is_notification_enabled(const uint8_t *in) { return (in[0] & 1u) != 0; }
static inline uint8_t uint32_encode(uint32_t value, uint8_t *out) {
  out[0] = value; out[1] = value >> 8; out[2] = value >> 16; out[3] = value >> 24;
  return 4;
}
''')
        cls.binaries = {}
        try:
            for api in ("s140_nrf52_6.1.1", "s140_nrf52_7.3.0", "s132_nrf52_6.1.1"):
                family = api.split("_")[0]
                headers = ROOT / "lib/softdevice" / api / (api + "_API/include")
                # Directory names omit the version in their API prefix.
                if not headers.is_dir():
                    headers = ROOT / "lib/softdevice" / api / (api + "_API") / "include"
                if not headers.is_dir():
                    raise AssertionError("missing real SoftDevice headers: " + str(headers))
                binary = cls.work / api
                sanitizers = (["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                               "-fno-pie", "-no-pie"] if sys.platform.startswith("linux") else [])
                result = subprocess.run([cls.cc, "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
                    "-DSVCALL_AS_NORMAL_FUNCTION", "-DNRF52840_XXAA", "-D__STATIC_INLINE=static inline",
                    "-DBLEGATT_ATT_MTU_MAX=247", *sanitizers,
                    "-I" + str(cls.work), "-I" + str(SOURCE.parent), "-I" + str(headers),
                    "-I" + str(headers / "nrf52"), "-I" + str(ROOT / "lib/nrfx/mdk"),
                    "-I" + str(ROOT / "src/cmsis/include"), str(cls.work / "main.c"), "-o", str(binary)],
                    text=True, capture_output=True, timeout=60)
                if result.returncode:
                    raise AssertionError(family + "\n" + result.stdout + result.stderr)
                cls.binaries[api] = binary
        except BaseException:
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_scenario(self, scenario):
        for api, binary in self.binaries.items():
            with self.subTest(api=api):
                result = subprocess.run([str(binary), str(scenario)], capture_output=True, text=True, timeout=30)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_attributes_keep_uuid_order_handles_permissions_lengths_and_values(self):
        self.run_scenario(0)

    def test_initialization_guards_and_each_service_error_are_unchanged(self):
        self.run_scenario(1)

    def test_notification_bytes_and_wide_value_casts_are_unchanged(self):
        self.run_scenario(2)

    def test_resource_retries_rebuild_packet_and_inout_length(self):
        self.run_scenario(3)

    def test_null_disconnected_and_uninitialized_guards_do_not_touch_packet(self):
        self.run_scenario(4)

    def test_all_control_opcodes_lengths_parameters_and_error_responses(self):
        self.run_scenario(5)

    def test_control_authorization_and_cccd_error_order_is_unchanged(self):
        self.run_scenario(6)


if __name__ == "__main__":
    unittest.main()
