#!/usr/bin/env python3
"""Host-only qualification of the exact RAK4631 internal/RAM/NOR/SD loader.

Builds isolated native fixtures, never invokes the ARM toolchain or flashes a
device. Existing Tower/RAK3401 tests remain independently runnable.
"""
from pathlib import Path
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TEST = ROOT / "test"
SRC = ROOT / "src"
FEATURES = ("MOTA_RAK_AUTO_STORE", "MOTA_QSPI_FLASH", "MOTA_SD_CARD",
            "MOTA_INTERNAL_BOOTLOADER_UPDATE")
BASE = ["-DOTA_DELTA_HOST_TEST", "-DDETOOLS_CONFIG_IN_PLACE_RESUME=0",
        "-DMOTA_RAK_AUTO_STORE=1", "-DMOTA_RAK_AUTO_RAK4631=1",
        "-DMOTA_QSPI_FLASH=1", "-DMOTA_INTERNAL_BOOTLOADER_UPDATE=1",
        "-DMOTA_RAM_ARENA_SIZE=65536", "-DUSB_DESC_VID=0x239A",
        "-DUSB_DESC_UF2_PID=0x0029", '-DDEVICE_NAME="4631_DFU"']
SD = ["-DMOTA_RAK_SD_STORE=1", "-DMOTA_SD_CARD=1"]
IDENTITY = ['-DTEST_HW_ID="NRF_BL_239A0029_4631_DFU"', "-DTEST_TARGET_ID=0x2D0DF000u"]


def make_policy_environment():
    # These policy-only child makes must use the flags generated for each
    # case, not a recursive `make sanitize` command-line CFLAGS override.
    # Keep the parent environment and all native fixture sanitizer flags intact.
    env = os.environ.copy()
    for variable in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES",
                     "CFLAGS", "LDFLAGS", "RECOVERY_ALLOW_ALL_BOARDS"):
        env.pop(variable, None)
    return env


class RakSdStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cc = os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc")
        if not cls.cc:
            raise unittest.SkipTest("a native C compiler is required")
        cls.temp = tempfile.TemporaryDirectory(prefix="rak-sd-store-")
        cls.directory = Path(cls.temp.name)
        cls.binaries = {}
        flags = ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Wno-unused-parameter"]
        if os.name != "nt":
            flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
        fixtures = {
            "apply": ("rak_sd_apply_test.c", BASE + SD),
            "internal": ("readback_test.c", BASE + SD),
            "boot-internal": ("bootloader_mota_test.c", BASE + SD + IDENTITY),
            "boot-sd-reject": ("bootloader_mota_test.c", BASE + SD + IDENTITY + ["-DTEST_RAK_SD_REJECT=1"]),
            # Compile the old adaptive policy (new SD macro absent) against a
            # successor image which already carries the supplemental marker.
            "old-loader-upgrade": ("bootloader_mota_test.c", BASE + IDENTITY + ["-DTEST_RAK_SD_SUCCESSOR=1"]),
            "retained-auth-shared": ("rak_retained_auth_test.c", BASE + SD),
            "retained-auth-legacy": ("rak_retained_auth_test.c", BASE),
        }
        try:
            for name, (source, defines) in fixtures.items():
                binary = cls.directory / name
                result = subprocess.run([
                    cls.cc, *flags, *defines, "-I", str(SRC), "-I", str(SRC / "detools"),
                    str(TEST / source), str(SRC / "detools/detools.c"),
                    str(SRC / "sha256.c"), str(SRC / "usb/uf2/bootloader_image.c"),
                    "-o", str(binary),
                ], text=True, capture_output=True, timeout=60)
                if result.returncode:
                    raise AssertionError(name + "\n" + result.stdout + result.stderr)
                cls.binaries[name] = binary
        except BaseException:
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_fixture(self, name, *arguments):
        result = subprocess.run([str(self.binaries[name]), *map(str, arguments)],
                                cwd=TEST, capture_output=True, text=True, timeout=60)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("FAIL", result.stdout)
        return result.stdout

    def test_sd_full_and_delta_apply_without_nor(self):
        for scenario in (0, 1):
            with self.subTest(scenario=scenario):
                self.assertIn("PASS", self.run_fixture("apply", scenario))

    def test_sd_auth_is_one_shot_fail_closed_before_probe(self):
        self.run_fixture("apply", 2)

    def test_sd_integrity_failure_cannot_fall_back(self):
        self.run_fixture("apply", 3)

    def test_nor_selectors_never_touch_sd(self):
        self.run_fixture("apply", 4)

    def test_legacy_and_unknown_hints_only_scan_conservative_internal_slot(self):
        self.run_fixture("apply", 5)

    def test_deployed_capability_bytes_are_unchanged(self):
        self.run_fixture("apply", 6)

    def test_internal_expanded_and_authenticated_ram_remain_working(self):
        self.assertIn("SUITE PASSED", self.run_fixture("internal"))

    def test_internal_bootloader_update_and_successor_capability_guards(self):
        output = self.run_fixture("boot-internal")
        self.assertIn("RAK3401 sharing USB board ID", output)
        self.assertIn("duplicate valid RAK SD capability", output)

    def test_sd_bootloader_handoff_is_rejected_without_probe_or_fallback(self):
        output = self.run_fixture("boot-sd-reject")
        self.assertIn("SD bootloader handoff is rejected without any SD/NOR probe", output)

    def test_deployed_adaptive_loader_accepts_additive_sd_successor(self):
        self.assertIn("SUITE PASSED", self.run_fixture("old-loader-upgrade"))

    def test_all_retained_auth_fields_and_geometry_match_legacy_contract(self):
        for name in ("retained-auth-shared", "retained-auth-legacy"):
            with self.subTest(profile=name):
                self.assertIn("PASS", self.run_fixture(name))

    def test_exact_rak_pins_and_other_boards_are_not_opted_in(self):
        source = r'''
#include <stdio.h>
#define NRF_SPIM2 2
#include "board.h"
#if defined(EXPECT_RAK_SD)
#ifndef MOTA_RAK_SD_STORE
#error "exact RAK4631 adaptive profile must advertise SD"
#endif
#ifdef MOTA_SD_POWER_PIN
#error "RAK15002 has unswitched power, not the sensor power rail"
#endif
int main(void) {
  printf("%u %u %u %u %u %u %u\n", MOTA_SD_CS_PIN, MOTA_SD_SCK_PIN,
    MOTA_SD_MISO_PIN, MOTA_SD_MOSI_PIN, MOTA_SD_SPIM,
    MOTA_QSPI_CSN_PIN, (USB_DESC_VID << 16) | USB_DESC_UF2_PID);
}
#else
#ifdef MOTA_RAK_SD_STORE
#error "RAK-only SD must not leak into other board profiles"
#endif
int main(void) { return 0; }
#endif
'''
        for board in ("wiscore_rak4631_auto", "wiscore_rak3401_auto",
                      "heltec_mesh_tower_v2", "wiscore_rak4631_board"):
            with self.subTest(board=board):
                output = self.directory / ("pins-" + board)
                flags = ["-DEXPECT_RAK_SD=1"] if board == "wiscore_rak4631_auto" else []
                built = subprocess.run([self.cc, "-std=c11", "-Wall", "-Werror", *flags,
                    "-x", "c", "-", "-I", str(SRC / "boards" / board), "-o", str(output)],
                    input=source, text=True, capture_output=True, timeout=20)
                self.assertEqual(0, built.returncode, built.stdout + built.stderr)
                result = subprocess.check_output([str(output)], text=True)
                if flags:
                    self.assertEqual([26, 3, 29, 30, 2, 31, 0x239A0029], list(map(int, result.split())))

    def test_c_profile_guard_rejects_partial_and_cross_board_combinations(self):
        valid = BASE + SD
        cases = [(valid, True)]
        for feature in (*FEATURES, "MOTA_RAK_AUTO_RAK4631"):
            cases.append(([flag for flag in valid if not flag.startswith("-D" + feature + "=")], False))
        cases.append(([flag for flag in valid if not flag.startswith("-DMOTA_RAM_ARENA_SIZE=")], False))
        cases.append(([flag.replace("ARENA_SIZE=65536", "ARENA_SIZE=32768") for flag in valid], False))
        cases.append((valid + ["-DMOTA_SD_DUAL_STORE=1"], False))
        cases.append((valid + ["-DMOTA_SD_BOOTLOADER_UPDATE=1"], False))
        cases.append((valid + ["-DMOTA_QSPI_BOOTLOADER_UPDATE=1"], False))
        cases.append(([flag for flag in valid if not flag.startswith("-DMOTA_RAK_AUTO_RAK4631=")]
                       + ["-DMOTA_RAK_AUTO_RAK3401=1"], False))
        cases.append(([flag for flag in valid if not flag.startswith("-DMOTA_RAK_SD_STORE=")], False))
        for index, (flags, expected) in enumerate(cases):
            with self.subTest(case=index):
                result = subprocess.run([self.cc, "-std=c11", "-fsyntax-only", *flags,
                    "-I", str(SRC), "-I", str(SRC / "detools"), "-x", "c", "-"],
                    input='#include "ota_delta.c"\n', capture_output=True, text=True, timeout=20)
                self.assertEqual(expected, result.returncode == 0, result.stdout + result.stderr)

    def test_cmake_and_make_storage_policy_matrix(self):
        if not shutil.which("cmake") or not shutil.which("make"):
            self.skipTest("native cmake and make are required for policy-only checks")
        valid = {"BOARD": "wiscore_rak4631_auto", "MCU_VARIANT": "nrf52840",
                 "MOTA_RAM_ARENA_SIZE": "65536", "MOTA_RAK_SD_STORE": "ON",
                 **{feature: "ON" for feature in FEATURES}}
        cases = [(valid, True)]
        for size in ("0x10000", "0X10000"):
            cases.append(({**valid, "MOTA_RAM_ARENA_SIZE": size}, True))
        for field, value in (("BOARD", "wiscore_rak3401_auto"), ("MCU_VARIANT", "nrf52833"),
                             ("MOTA_RAM_ARENA_SIZE", "0"), ("MOTA_RAM_ARENA_SIZE", ""),
                             ("MOTA_SD_DUAL_STORE", "ON"),
                             ("MOTA_SD_BOOTLOADER_UPDATE", "ON"),
                             ("MOTA_QSPI_BOOTLOADER_UPDATE", "ON")):
            cases.append(({**valid, field: value}, False))
        for feature in FEATURES:
            cases.append(({**valid, feature: "OFF"}, False))
        cases.append(({**valid, "MOTA_RAK_SD_STORE": "OFF"}, False))
        # Preserve valid pre-existing adaptive RAK and SD/internal Tower mixes.
        cases.append(({key: value for key, value in valid.items()
                       if key not in {"MOTA_RAK_SD_STORE", "MOTA_SD_CARD", "MOTA_SD_BOOTLOADER_UPDATE"}}, True))
        cases.append(({"BOARD": "heltec_mesh_tower_v2", "MCU_VARIANT": "nrf52840",
                       "MOTA_SD_CARD": "ON", "MOTA_SD_DUAL_STORE": "ON",
                       "MOTA_SD_BOOTLOADER_UPDATE": "ON", "MOTA_INTERNAL_BOOTLOADER_UPDATE": "ON",
                       "MOTA_RAM_ARENA_SIZE": "65536"}, True))
        make_source = (ROOT / "Makefile").read_text(encoding="utf-8")
        make_guard = make_source[make_source.index("mota_feature_flag ="):make_source.index("# Internal-update profiles")]
        for index, (settings, expected) in enumerate(cases):
            with self.subTest(case=index, settings=settings):
                script = self.directory / "guard.cmake"
                script.write_text("\n".join(f'set({key} "{value}")' for key, value in settings.items()) +
                                  f'\ninclude("{(ROOT / "cmake/mota_storage_policy.cmake").as_posix()}")\n')
                checked = subprocess.run(["cmake", "-P", str(script)], capture_output=True, text=True, timeout=15)
                self.assertEqual(expected, checked.returncode == 0, checked.stdout + checked.stderr)
                features = [f"-D{key}=1" for key, value in settings.items()
                            if key.startswith("MOTA_") and key != "MOTA_RAM_ARENA_SIZE" and value == "ON"]
                makefile = self.directory / "guard.mk"
                makefile.write_text("BOARD := " + settings.get("BOARD", "") +
                    "\nMCU_SUB_VARIANT := " + settings.get("MCU_VARIANT", "") +
                    "\nMOTA_RAM_ARENA_SIZE := " + settings.get("MOTA_RAM_ARENA_SIZE", "") +
                    "\nCFLAGS := " + " ".join(features) + "\n" + make_guard + "\nguard:; @true\n")
                checked = subprocess.run(["make", "-s", "-f", str(makefile), "guard"],
                                         env=make_policy_environment(),
                                         capture_output=True, text=True, timeout=15)
                self.assertEqual(expected, checked.returncode == 0, checked.stdout + checked.stderr)

    def test_storage_policy_matrix_ignores_recursive_make_overrides(self):
        if not shutil.which("cmake") or not shutil.which("make"):
            self.skipTest("native cmake and make are required for policy-only checks")
        recipe = " ".join(shlex.quote(value) for value in (
            sys.executable, str(Path(__file__).resolve()),
            "RakSdStoreTests.test_cmake_and_make_storage_policy_matrix"))
        makefile = "policy-regression:\n\t" + recipe + "\n"
        pollution = {"CFLAGS": "-O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer",
                     "LDFLAGS": "-fsanitize=address,undefined",
                     "BOARD": "wiscore_rak3401_auto", "MOTA_RAM_ARENA_SIZE": "0"}
        for environment_overrides in (False, True):
            with self.subTest(environment_overrides=environment_overrides):
                env = make_policy_environment()
                env.update(pollution)
                command = ["make", "--no-print-directory", "-f", "-"]
                if environment_overrides:
                    # -e and exported variables are inherited through
                    # MAKEFLAGS; normal `:=` assignments cannot override them.
                    command.append("--environment-overrides")
                else:
                    # Real command-line overrides are exported by Make through
                    # MAKEFLAGS/MAKEOVERRIDES to its Python recipe and children.
                    command.extend(f"{key}={value}" for key, value in pollution.items())
                command.append("policy-regression")
                checked = subprocess.run(command, input=makefile, env=env,
                                         capture_output=True, text=True, timeout=60)
                self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
                self.assertIn("Ran 1 test", checked.stderr)
                self.assertNotIn("FAILED", checked.stderr)


if __name__ == "__main__":
    unittest.main()
