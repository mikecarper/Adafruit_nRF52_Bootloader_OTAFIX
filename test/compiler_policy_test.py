#!/usr/bin/env python3
"""Host-only qualification of shared compiler selection and RAK LTO flags."""
from pathlib import Path
import os
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import compiler_policy
FLAGS = ("-fno-schedule-insns", "-fno-schedule-insns2", "-fno-code-hoisting",
         "-fno-tree-ter", "-fno-tree-dominator-opts", "-fno-tree-tail-merge",
         "-fno-optimize-sibling-calls", "-fno-if-conversion", "-mbranch-cost=3",
         "-fno-tree-loop-im", "-fno-early-inlining")
RAK = "wiscore_rak4631_auto"


def isolated_make_environment():
    """Keep recursive host-test flags from replacing firmware board options."""
    env = os.environ.copy()
    for variable in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES",
                     "CFLAGS", "LDFLAGS", "RECOVERY_ALLOW_ALL_BOARDS"):
        env.pop(variable, None)
    return env


class CompilerPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("cmake") or not shutil.which("make"):
            raise unittest.SkipTest("host cmake and make are required; no ARM compiler is invoked")
        cls.temp = tempfile.TemporaryDirectory(prefix="otafix-compiler-policy-")
        cls.work = Path(cls.temp.name)
        cls.compiler = cls.work / "fake-gcc"
        cls.compiler.write_text("#!" + sys.executable + "\nimport os\n"
                                "print(os.environ['OTAFIX_FAKE_GCC_VERSION'])\n")
        cls.compiler.chmod(0o755)
        cls.tool_bin = cls.work / "selected-bin"
        cls.tool_bin.mkdir()
        (cls.tool_bin / "arm-none-eabi-gcc").symlink_to(cls.compiler)
        cls.script = cls.work / "compiler-policy.cmake"
        cls.script.write_text('include("' + (ROOT / "cmake/mota_compiler_policy.cmake").as_posix() + '")\n'
                              'mota_require_arm_gcc("${TEST_ID}" "${TEST_VERSION}")\n'
                              'message(STATUS "MINIMUM=${MOTA_ARM_GCC_MINIMUM}")\n'
                              'message(STATUS "OPTIONS=${MOTA_RAK_SD_SIZE_OPTIONS}")\n')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def cmake_policy(self, board, version, *, combined=False, compiler="GNU", extra=()):
        return subprocess.run(["cmake", "-DBOARD=" + board, "-DTEST_ID=" + compiler,
                               "-DTEST_VERSION=" + version,
                               "-DMOTA_RAK_SD_STORE=" + ("ON" if combined else "OFF"),
                               *extra, "-P", str(self.script)], capture_output=True, text=True, timeout=15)

    def make_variable(self, name, *, board=RAK, version="15.3.1", recovery=False,
                      test_version="0x02040B7E", git_tag=None):
        env = isolated_make_environment()
        env["OTAFIX_FAKE_GCC_VERSION"] = version
        command = ["make", "--no-print-directory", "BOARD=" + board,
                   "CC=" + str(self.compiler), "PYTHON=" + sys.executable,
                   "RECOVERY_ALLOW_ALL_BOARDS=" + str(int(recovery))]
        if test_version is not None:
            command += ["MOTA_BOOTLOADER_TEST_BUILD=1",
                        "MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=" + test_version]
        if git_tag is not None:
            command += ["GIT_VERSION=" + git_tag]
        return subprocess.run([*command, "print-" + name], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=30)

    def cmake_labels(self, board, git_tag, packed, *, test_version=None, recovery=False):
        source = (ROOT / "CMakeLists.txt").read_text()
        start = source.index('set(FIRMWARE_VERSION "${GIT_VERSION}")')
        stop = source.index('target_compile_definitions(bootloader PUBLIC\n  UF2_VERSION_BASE=', start)
        script = self.work / "labels.cmake"
        variables = dict(BOARD=board, GIT_VERSION=git_tag, GIT_VERSION_BASE=git_tag,
                         MOTA_BOOTLOADER_VERSION=packed, SD_NAME="s140", SD_VERSION="6.1.1",
                         MOTA_RAK_SD_STORE="ON" if board == RAK else "OFF",
                         RECOVERY_ALLOW_ALL_BOARDS="ON" if recovery else "OFF")
        if test_version is not None:
            variables["MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE"] = test_version
        script.write_text("\n".join(f'set({key} "{value}")' for key, value in variables.items()) +
                          "\n" + source[start:stop] + "\n" +
                          "\n".join(f'message(STATUS "{key}=${{{key}}}")' for key in
                                    ("FIRMWARE_VERSION", "FIRMWARE_VERSION_BASE",
                                     "BLE_FIRMWARE_VERSION", "GIT_VERSION", "MOTA_BOOTLOADER_VERSION")))
        result = subprocess.run(["cmake", "-P", str(script)], capture_output=True,
                                text=True, timeout=15)
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout

    def test_cmake_rejects_older_compiler_only_for_the_combined_profile(self):
        for version in ("14.2.1", "14.3.1", "15.2.1"):
            result = self.cmake_policy(RAK, version, combined=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("15.3.Rel1", result.stderr)
            self.assertIn("ARM_GNU_RELEASE=15.3.rel1", result.stderr)
        for board in ("heltec_t096", "heltec_t114", "wiscore_rak3401_auto",
                      "heltec_mesh_tower_v2_sdcard"):
            result = self.cmake_policy(board, "14.2.1")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("MINIMUM=14.2", result.stdout)
            self.assertNotIn(FLAGS[0], result.stdout)

    def test_cmake_keeps_gnu_requirement_and_existing_minimum(self):
        for compiler, version in (("Clang", "19.0"), ("GNU", "14.1.0")):
            result = self.cmake_policy("heltec_t096", version, compiler=compiler)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("14.2.Rel1", result.stderr)
        # The old adaptive profile, with no supplemental SD macro, stays14.2.
        self.assertEqual(0, self.cmake_policy(RAK, "14.2.1").returncode)

    def test_cmake_flags_are_complete_and_reach_compile_and_lto_link(self):
        result = self.cmake_policy(RAK, "15.3.1", combined=True)
        self.assertEqual(0, result.returncode, result.stderr)
        for flag in FLAGS:
            self.assertIn(flag, result.stdout)
        source = (ROOT / "CMakeLists.txt").read_text()
        self.assertIn('mota_require_arm_gcc("${CMAKE_C_COMPILER_ID}" "${CMAKE_C_COMPILER_VERSION}")', source)
        for phase in ("compile", "link"):
            self.assertIn("target_" + phase + "_options(bootloader PRIVATE ${MOTA_RAK_SD_SIZE_OPTIONS})", source)
        self.assertLess(source.index("-Wno-unused-parameter"),
                        source.index("if (MOTA_RAK_SD_SIZE_OPTIONS)"))
        self.assertNotIn("-fmerge-all-constants", result.stdout)

    def test_make_minimum_guard_has_helpful_early_diagnostics(self):
        rejected = self.make_variable("CFLAGS", version="14.2.1")
        self.assertNotEqual(0, rejected.returncode)
        self.assertIn("15.3.Rel1", rejected.stderr)
        self.assertIn("ARM_GNU_RELEASE=15.3.rel1", rejected.stderr)
        for board in ("heltec_t096", "wiscore_rak3401_auto"):
            accepted = self.make_variable("ARM_GCC_MINIMUM", board=board, version="14.2.1")
            self.assertEqual(0, accepted.returncode, accepted.stderr)
            self.assertIn("ARM_GCC_MINIMUM = 14.2", accepted.stdout)

    def test_make_flags_apply_to_normal_recovery_compile_and_lto(self):
        for recovery in (False, True):
            for variable in ("CFLAGS", "LDFLAGS"):
                result = self.make_variable(variable, recovery=recovery)
                self.assertEqual(0, result.returncode, result.stderr)
                for flag in FLAGS:
                    self.assertIn(flag, result.stdout)
                self.assertNotIn("-fmerge-all-constants", result.stdout)
        unchanged = self.make_variable("CFLAGS", board="wiscore_rak3401_auto", version="14.2.1")
        self.assertNotIn(FLAGS[0], unchanged.stdout)

    def test_ci_selects_each_board_from_the_shared_table(self):
        for name in ("githubci.yml", "recovery.yml"):
            workflow = (ROOT / ".github/workflows" / name).read_text()
            self.assertIn("tools/compiler_policy.py --board '${{ matrix.board }}'", workflow)
            self.assertIn("release: ${{ steps.compiler.outputs.release }}", workflow)
            self.assertNotIn("matrix.board == 'wiscore_rak4631_auto' &&", workflow)
        workflow = (ROOT / ".github/workflows/githubci.yml").read_text()
        self.assertIn("board: [heltec_t096, heltec_t114]", workflow)
        self.assertEqual(2, workflow.count("release: ${{ steps.compiler.outputs.release }}"))
        self.assertIn("ARG ARM_GNU_RELEASE=14.2.rel1", (ROOT / "Dockerfile").read_text())

    def test_policy_table_contains_only_known_boards_and_qualified_releases(self):
        policy = json.loads(compiler_policy.POLICY_PATH.read_text())
        self.assertEqual("14.2.Rel1", policy["default_release"])
        self.assertEqual("15.3.Rel1", compiler_policy.preferred_release(RAK))
        for board, release in policy["board_releases"].items():
            self.assertTrue((ROOT / "src/boards" / board / "board.mk").is_file(), board)
            self.assertIn(release, ("14.2.Rel1", "15.3.Rel1"))

    def test_default_make_resolves_selected_family_and_rejects_unqualified_path(self):
        env = isolated_make_environment()
        env["ARM_GNU_TOOLCHAIN_15_3"] = str(self.tool_bin)
        env["OTAFIX_FAKE_GCC_VERSION"] = "15.3.1"
        command = ["make", "--no-print-directory", "BOARD=" + RAK,
                   "PYTHON=" + sys.executable, "MOTA_BOOTLOADER_TEST_BUILD=1",
                   "MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=0x02040B7E", "print-CC"]
        accepted = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertIn(str(self.tool_bin / "arm-none-eabi-gcc"), accepted.stdout)
        env["OTAFIX_FAKE_GCC_VERSION"] = "16.2.0"
        rejected = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertNotEqual(0, rejected.returncode)
        self.assertIn("selects Arm GNU 15.3.Rel1; found 16.2.0", rejected.stderr)
        self.assertIn("ARM_GNU_TOOLCHAIN_15_3", rejected.stderr)

    def test_missing_optional_install_root_falls_back_to_matching_path(self):
        env = os.environ.copy()
        env.update(ARM_GNU_TOOLCHAIN_15_3=str(self.work / "not-installed"),
                   OTAFIX_FAKE_GCC_VERSION="15.3.2",
                   PATH=str(self.tool_bin) + os.pathsep + env["PATH"])
        result = subprocess.run([sys.executable, str(ROOT / "tools/compiler_policy.py"),
                                 "--board", RAK, "--field", "prefix"],
                                env=env, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(str(self.tool_bin / "arm-none-eabi-"), result.stdout.strip())

    def test_windows_executable_suffix_is_removed_before_selecting_sibling_tools(self):
        for suffix in ("gcc.exe", "gcc.EXE", "gcc.Exe"):
            compiler = "C:/Arm/bin/arm-none-eabi-" + suffix
            with self.subTest(suffix=suffix), \
                 mock.patch.object(compiler_policy.shutil, "which", return_value=compiler), \
                 mock.patch.object(compiler_policy, "compiler_version", return_value=((15, 3), "15.3.1")):
                self.assertEqual("C:/Arm/bin/arm-none-eabi-", compiler_policy.toolchain_prefix(RAK))

    def test_default_make_runs_compiler_from_installation_with_spaces(self):
        root = self.work / "qualified tools"
        directory = root / "bin"
        directory.mkdir(parents=True)
        (directory / "arm-none-eabi-gcc").symlink_to(self.compiler)
        env = isolated_make_environment()
        env.update(ARM_GNU_TOOLCHAIN_15_3=str(root), OTAFIX_FAKE_GCC_VERSION="15.3.1")
        command = ["make", "--no-print-directory", "BOARD=" + RAK,
                   "PYTHON=" + sys.executable, "MOTA_BOOTLOADER_TEST_BUILD=1",
                   "MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=0x02040B7E", "print-CC",
                   "print-ARM_GCC_VERSION"]
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("CC = " + str(directory / "arm-none-eabi-gcc"), result.stdout)
        self.assertIn("ARM_GCC_VERSION = 15.3.1", result.stdout)

    def test_cmake_resolves_a_relative_qualification_prefix_on_path(self):
        with mock.patch.dict(os.environ, {"PATH": str(self.tool_bin) + os.pathsep + os.environ["PATH"]}):
            result = self.cmake_policy(RAK, "15.3.1", combined=True,
                                      extra=("-DARM_GNU_SELECTED_PREFIX=arm-none-eabi-",
                                             "-DCMAKE_C_COMPILER=" + str(self.tool_bin / "arm-none-eabi-gcc")))
        self.assertEqual(0, result.returncode, result.stderr)

    def test_ordinary_environment_cc_does_not_bypass_the_selected_compiler(self):
        old_bin = self.work / "old-path-bin"
        old_bin.mkdir()
        old_compiler = old_bin / "arm-none-eabi-gcc"
        old_compiler.write_text("#!" + sys.executable + "\nprint('14.2.1')\n")
        old_compiler.chmod(0o755)
        env = isolated_make_environment()
        env.update(CC="gcc", ARM_GNU_TOOLCHAIN_15_3=str(self.tool_bin),
                   OTAFIX_FAKE_GCC_VERSION="15.3.1",
                   PATH=str(old_bin) + os.pathsep + env["PATH"])
        command = ["make", "--no-print-directory", "BOARD=" + RAK,
                   "PYTHON=" + sys.executable, "MOTA_BOOTLOADER_TEST_BUILD=1",
                   "MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=0x02040B7E", "print-CC",
                   "print-ARM_GCC_VERSION"]
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("CC = " + str(self.tool_bin / "arm-none-eabi-gcc"), result.stdout)
        self.assertIn("ARM_GCC_VERSION = 15.3.1", result.stdout)

    def test_cmake_rejects_cached_compiler_after_selection_changes(self):
        result = self.cmake_policy(RAK, "15.3.1", combined=True,
                                   extra=("-DARM_GNU_SELECTED_PREFIX=" + str(self.tool_bin / "arm-none-eabi-"),
                                          "-DCMAKE_C_COMPILER=/cached/arm-none-eabi-gcc"))
        self.assertNotEqual(0, result.returncode)
        self.assertIn("fresh build directory", " ".join(result.stderr.split()))

    def test_gnu_c17_does_not_reach_assembly(self):
        cflags = self.make_variable("CFLAGS")
        assembly = self.make_variable("ASFLAGS")
        self.assertIn("-std=gnu17", cflags.stdout)
        self.assertNotIn("-std=", assembly.stdout)
        cmake = (ROOT / "CMakeLists.txt").read_text()
        self.assertIn("$<$<COMPILE_LANGUAGE:C>:-std=gnu17>", cmake)

    def test_cmake_rak_production_labels_keep_complete_version_with_fixed_length(self):
        for tag, packed in (("0.11.0-OTAFIX2.4.11-preview.1", "0x02040B01"),
                            ("0.11.0-OTAFIX2.4.11", "0x02040BFF"),
                            ("123.234.245-OTAFIX254.253.252-preview.254", "0xFEFDFCFE")):
            label = "BL_" + packed
            self.assertEqual(13, len(label))
            output = self.cmake_labels(RAK, tag, packed)
            for key in ("FIRMWARE_VERSION", "FIRMWARE_VERSION_BASE"):
                self.assertIn(key + "=" + label + "\n", output)
            self.assertIn("BLE_FIRMWARE_VERSION=" + label + " s140 6.1.1", output)
            self.assertIn("GIT_VERSION=" + tag, output)
            self.assertIn("MOTA_BOOTLOADER_VERSION=" + packed, output)
            other = self.cmake_labels("wiscore_rak3401_auto", tag, packed)
            self.assertIn("FIRMWARE_VERSION=" + tag, other)

    def test_test_and_recovery_labels_keep_precedence_in_both_build_paths(self):
        tag = "0.11.0-OTAFIX2.4.11-preview.126"
        packed = "0x02040B7E"
        for recovery, prefix in ((False, "TEST_"), (True, "R_")):
            expected = prefix + packed
            output = self.cmake_labels(RAK, tag, packed, test_version=packed, recovery=recovery)
            self.assertIn("FIRMWARE_VERSION=" + expected + "\n", output)
            for variable in ("FIRMWARE_VERSION", "FIRMWARE_VERSION_BASE", "BLE_FIRMWARE_VERSION"):
                result = self.make_variable(variable, recovery=recovery, git_tag=tag)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn(variable + " = " + expected, result.stdout)
            # Test/recovery labels never get replaced by the production BL_.
            self.assertNotIn("BL_", output)
        self.assertGreater(len("TEST_" + packed), len("BL_" + packed))

    def test_make_production_label_changes_only_exact_rak_not_filenames_or_manifest(self):
        tag = "0.11.0-OTAFIX2.4.11-preview.126"
        packed = "0x02040B7E"
        for variable, expected in (
            ("FIRMWARE_VERSION", "BL_" + packed),
            ("FIRMWARE_VERSION_BASE", "BL_" + packed),
            ("BLE_FIRMWARE_VERSION", "BL_" + packed + " s140 6.1.1"),
            ("MOTA_BOOTLOADER_VERSION", packed),
            ("OUT_NAME", RAK + "_bootloader-" + tag),
        ):
            result = self.make_variable(variable, test_version=None, git_tag=tag)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn(variable + " = " + expected + "\n", result.stdout)
        other = self.make_variable("FIRMWARE_VERSION", board="wiscore_rak3401_auto",
                                   version="14.2.1", test_version=None, git_tag=tag)
        self.assertEqual(0, other.returncode, other.stderr)
        self.assertIn("FIRMWARE_VERSION = " + tag + "\n", other.stdout)
        recovery = self.make_variable("OUT_NAME", recovery=True, test_version=None,
                                      git_tag="R_" + tag)
        self.assertEqual(0, recovery.returncode, recovery.stderr)
        self.assertIn("OUT_NAME = R_" + RAK + "_bootloader-" + tag + "\n", recovery.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
