#!/usr/bin/env python3
"""Check electrically distinct ports and keep untested images out of releases."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_bootloader_mota_release import PENDING_BOARDS, QUALIFIED_BOARDS, ci_boards


class PendingBoardTests(unittest.TestCase):
    def test_pending_ports_have_no_released_download(self):
        expected = {"gat562_mesh_watch13", "lilygo_techo_card", "lilygo_t_impulse_plus",
                    "muzi_base", "meshtiny", "nano_g2_ultra", "thinknode_m8"}
        self.assertEqual(expected, PENDING_BOARDS)
        self.assertFalse(expected.intersection(QUALIFIED_BOARDS))
        mapping = json.loads((ROOT / "docs/bootloader_profiles.json").read_text())
        unavailable = {p["id"] for p in mapping["unavailableProfiles"]}
        self.assertTrue(expected.issubset(unavailable))
        self.assertTrue(expected.issubset(ci_boards()))
        self.assertFalse(expected.intersection(ci_boards(production=True)))
        self.assertTrue(set(QUALIFIED_BOARDS).issubset(ci_boards(production=True)))
        for board in expected:
            directory = ROOT / "src/boards" / board
            cmake = (directory / "board.cmake").read_text()
            make = (directory / "board.mk").read_text()
            self.assertIn("set(MOTA_QSPI_BOOTLOADER_UPDATE ON)", cmake)
            self.assertIn("-DMOTA_QSPI_BOOTLOADER_UPDATE=1", make)
            # NFC must survive both build systems on the Card.
            if board == "lilygo_techo_card":
                self.assertIn("set(USE_NFCT yes)", cmake)
                self.assertIn("USE_NFCT = yes", make)

    def test_compiled_pin_contracts(self):
        expected = {
            "gat562_mesh_watch13": [0, 1, 9, 10, 3, 26, 30, 29, 28, 2, 0x239A0029],
            "lilygo_techo_card": [0, 0, 24, 24, 4, 12, 6, 8, 41, 26, 0x239A00DA],
            "lilygo_t_impulse_plus": [1, 0, 24, 24, 4, 12, 6, 41, 8, 26, 0x239A00DA],
            "muzi_base": [2, 0, 10, 10, 3, 26, 30, 29, 28, 2, 0x239A0081],
            "meshtiny": [2, 1, 9, 4, 3, 22, 27, 29, 21, 2, 0x239A0029],
            "nano_g2_ultra": [0, 0, 38, 38, 8, 39, 6, 26, 36, 34, 0x42518695],
            "thinknode_m8": [0, 1, 12, 12, 46, 47, 44, 45, 7, 5, 0],
        }
        source = '''#include <stdio.h>
#define PINNUM(p,n) ((p)*32+(n))
#include "board.h"
int main(void) {
  printf("%u %u %u %u %u %u %u %u %u %u %u\\n", LEDS_NUMBER, LED_STATE_ON,
    BUTTON_DFU, BUTTON_DFU_OTA, MOTA_QSPI_SCK_PIN, MOTA_QSPI_CSN_PIN,
    MOTA_QSPI_IO0_PIN, MOTA_QSPI_IO1_PIN, MOTA_QSPI_IO2_PIN, MOTA_QSPI_IO3_PIN,
    (USB_DESC_VID << 16) | USB_DESC_UF2_PID);
}
'''
        with tempfile.TemporaryDirectory() as temp:
            output = str(Path(temp) / "pins")
            for board, values in expected.items():
                with self.subTest(board=board):
                    flags = ["-DOTAFIX_M8_COMPILE_ONLY=1"] if board == "thinknode_m8" else []
                    subprocess.run(["cc", "-Wall", "-Werror", *flags, "-x", "c", "-",
                                    "-I", str(ROOT / "src/boards" / board), "-o", output],
                                   input=source, text=True, check=True, capture_output=True)
                    self.assertEqual(values, list(map(int, subprocess.check_output([output]).split())))

    def test_motor_and_flash_power_hooks(self):
        source = '''#include <assert.h>
#include "boards.h"
static unsigned output[48], level[48];
void nrf_gpio_cfg_output(unsigned p) { assert(p < 48); output[p] = 1; }
void nrf_gpio_pin_clear(unsigned p) { assert(p < 48); level[p] = 0; }
void nrf_gpio_pin_set(unsigned p) { assert(p < 48); level[p] = 1; }
void board_init2(void);
void board_teardown2(void);
int main(void) {
  board_init2();
  assert(output[CHECK_PIN] && level[CHECK_PIN] == CHECK_ON);
  board_teardown2();
  assert(level[CHECK_PIN] == 0);
}
'''
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            (temp / "uf2").mkdir()
            (temp / "uf2/configkeys.h").write_text("#define CFG_MAGIC0 1\n#define CFG_MAGIC1 2\n")
            (temp / "boards.h").write_text('''#include <stdint.h>
#define PINNUM(p,n) ((p)*32+(n))
#include "board.h"
void nrf_gpio_cfg_output(unsigned);
void nrf_gpio_pin_clear(unsigned);
void nrf_gpio_pin_set(unsigned);
''')
            for board, pin, on in (("gat562_mesh_watch13", 36, 0),
                                   ("lilygo_techo_card", 30, 1),
                                   ("lilygo_t_impulse_plus", 14, 1)):
                with self.subTest(board=board):
                    directory = ROOT / "src/boards" / board
                    output = str(temp / "hooks")
                    subprocess.run(["cc", "-Wall", "-Werror", "-x", "c", "-",
                                    str(directory / "pinconfig.c"), "-I", str(temp), "-I", str(directory),
                                    f"-DCHECK_PIN={pin}", f"-DCHECK_ON={on}", "-o", output],
                                   input=source, text=True, check=True, capture_output=True)
                    subprocess.run([output], check=True)

    def test_m8_requires_test_build_and_version(self):
        for options, reason in (([], "compile-only"),
                                (["MOTA_BOOTLOADER_TEST_BUILD=1"], "explicit test version")):
            with self.subTest(options=options):
                make = subprocess.run(["make", "-n", "BOARD=thinknode_m8", *options, "all"],
                                      cwd=ROOT, text=True, capture_output=True)
                self.assertNotEqual(make.returncode, 0)
                self.assertIn(reason, make.stdout + make.stderr)
                with tempfile.TemporaryDirectory() as temp:
                    cmake_options = ["-D" + option for option in options]
                    cmake = subprocess.run(["cmake", "-S", str(ROOT), "-B", temp,
                                            "-DBOARD=thinknode_m8", *cmake_options],
                                           text=True, capture_output=True)
                    self.assertNotEqual(cmake.returncode, 0)
                    self.assertIn(reason, cmake.stdout + cmake.stderr)

        header = subprocess.run(["cc", "-x", "c", "-", "-fsyntax-only", "-I",
                                 str(ROOT / "src/boards/thinknode_m8")],
                                input='#include "board.h"\n', text=True, capture_output=True)
        self.assertNotEqual(header.returncode, 0)
        self.assertIn("compile-only", header.stderr)

    def test_m8_peripheral_hooks_do_not_drive_m1_led_or_other_controls(self):
        source = '''#include <assert.h>
#include "boards.h"
static unsigned output[48], level[48], touched[48];
void nrf_gpio_cfg_output(unsigned p) {
  assert(p < 48); assert(touched[p] && !level[p]); output[p] = 1;
}
void nrf_gpio_pin_clear(unsigned p) { assert(p < 48); touched[p] = 1; level[p] = 0; }
void board_init2(void);
void board_teardown2(void);
int main(void) {
  for (unsigned i = 0; i < 48; ++i) level[i] = 1;
  board_init2();
  for (unsigned i = 0; i < 48; ++i) {
    unsigned off = i == 16 || i == 33 || i == 40 || i == 42 || i == 43;
    assert(output[i] == off && touched[i] == off && level[i] == !off);
    output[i] = touched[i] = 0; level[i] = 1;
  }
  board_teardown2();
  for (unsigned i = 0; i < 48; ++i) {
    unsigned off = i == 16 || i == 33 || i == 40 || i == 42 || i == 43;
    assert(output[i] == off && touched[i] == off && level[i] == !off);
  }
}
'''
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            (temp / "uf2").mkdir()
            (temp / "uf2/configkeys.h").write_text("#define CFG_MAGIC0 1\n#define CFG_MAGIC1 2\n")
            (temp / "boards.h").write_text('''#include <stdint.h>
#define PINNUM(p,n) ((p)*32+(n))
#include "board.h"
void nrf_gpio_cfg_output(unsigned);
void nrf_gpio_pin_clear(unsigned);
''')
            directory = ROOT / "src/boards/thinknode_m8"
            output = str(temp / "hooks")
            subprocess.run(["cc", "-Wall", "-Werror", "-DOTAFIX_M8_COMPILE_ONLY=1", "-x", "c", "-",
                            str(directory / "pinconfig.c"), "-I", str(temp), "-I", str(directory),
                            "-o", output], input=source, text=True, check=True, capture_output=True)
            subprocess.run([output], check=True)


if __name__ == "__main__":
    unittest.main()
