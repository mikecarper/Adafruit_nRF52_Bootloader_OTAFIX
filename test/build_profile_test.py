#!/usr/bin/env python3
"""Host regression for Make build-profile cache invalidation and CI lineage."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT / "Makefile"
WORKFLOW = ROOT / ".github" / "workflows" / "githubci.yml"
QUALIFICATION_VERSION = "0x02040601"


FAKE_TOOL = r"""#!/usr/bin/env python3
import os
from pathlib import Path
import sys

args = sys.argv[1:]
if "-dumpfullversion" in args or "-dumpversion" in args:
    print("14.2.1")
    raise SystemExit(0)

def option_value(option):
    try:
        return args[args.index(option) + 1]
    except (ValueError, IndexError):
        return None

output = option_value("-o")
if output is None:
    raise SystemExit(0)

kind = "compile" if "-c" in args else "link"
output_path = Path(output)
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_bytes((kind + "\n").encode("ascii"))

depfile = option_value("-MF")
if depfile is not None:
    depfile_path = Path(depfile)
    depfile_path.parent.mkdir(parents=True, exist_ok=True)
    depfile_path.write_text(f"{output}:\n", encoding="utf-8")

with Path(os.environ["OTAFIX_FAKE_CC_LOG"]).open("a", encoding="utf-8") as stream:
    stream.write(f"{kind}\t{output}\n")
"""


class BuildProfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="otafix-profile-")
        self.work = Path(self.tempdir.name)
        self.build = self.work / "build"
        self.bin = self.work / "bin"
        self.log = self.work / "compiler.log"
        self.tool_prefix = self.work / "fake-arm-none-eabi-"

        gcc = Path(f"{self.tool_prefix}gcc")
        gcc.write_text(FAKE_TOOL, encoding="utf-8")
        gcc.chmod(0o755)
        for tool in ("size", "objcopy", "as", "gdb"):
            Path(f"{self.tool_prefix}{tool}").symlink_to(gcc)

        self.env = os.environ.copy()
        for inherited_make_var in (
            "MAKEFLAGS",
            "MFLAGS",
            "MAKELEVEL",
            "MAKEOVERRIDES",
            "SD_NAME",
            "SD_VERSION",
            "SIGNED_FW",
            "SIGNED_FW_QX",
            "SIGNED_FW_QY",
            "DUALBANK_FW",
            "FORCE_UF2",
            "DEFAULT_TO_OTA_DFU",
            "DEBUG",
            "DFU_USB_ENUMERATION_TIMEOUT_MS",
            "MOTA_RAM_ARENA_SIZE",
            "USE_NFCT",
            "ANT_LICENSE_KEY",
            "CFLAGS",
            "ASFLAGS",
            "LDFLAGS",
            "LIBS",
        ):
            self.env.pop(inherited_make_var, None)
        self.env["OTAFIX_FAKE_CC_LOG"] = str(self.log)

        self.common = [
            "make",
            "--no-print-directory",
            f"BOARD=heltec_t096",
            f"BUILD={self.build}",
            f"BIN={self.bin}",
            f"CROSS_COMPILE={self.tool_prefix}",
            f"PYTHON={sys.executable}",
            "MOTA_BOOTLOADER_TEST_BUILD=1",
            f"MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE={QUALIFICATION_VERSION}",
        ]

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def make(self, target: str, *variables: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*self.common, *variables, target],
            cwd=ROOT,
            env=self.env,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def make_variable(self, name: str, *variables: str) -> str:
        result = self.make(f"print-{name}", *variables)
        prefix = f"{name} = "
        for line in reversed(result.stdout.splitlines()):
            if line.startswith(prefix):
                return line[len(prefix) :]
        self.fail(f"make did not print {name}:\n{result.stdout}\n{result.stderr}")

    def profile(self, *variables: str) -> tuple[Path, str]:
        self.make("build-profile", *variables)
        stamp = Path(self.make_variable("PROFILE_STAMP", *variables))
        digest = stamp.read_text(encoding="ascii").strip()
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertFalse(Path(f"{stamp}.candidate").exists())
        return stamp, digest

    def compiler_events(self, kind: str) -> list[str]:
        if not self.log.exists():
            return []
        return [
            line
            for line in self.log.read_text(encoding="utf-8").splitlines()
            if line.startswith(f"{kind}\t")
        ]

    def test_material_profiles_invalidate_objects_and_link_output(self) -> None:
        stamp, baseline = self.profile()
        baseline_stat = stamp.stat()

        same_stamp, same_digest = self.profile()
        self.assertEqual(stamp, same_stamp)
        self.assertEqual(baseline, same_digest)
        self.assertEqual(baseline_stat.st_ino, same_stamp.stat().st_ino)
        self.assertEqual(baseline_stat.st_mtime_ns, same_stamp.stat().st_mtime_ns)

        variants = {
            "SoftDevice name": ("SD_NAME=s132",),
            "SoftDevice version": ("SD_VERSION=7.3.0",),
            "signed firmware": (
                "SIGNED_FW=1",
                "SIGNED_FW_QX=0x01,0x02",
                "SIGNED_FW_QY=0x03,0x04",
            ),
            "dual bank": ("DUALBANK_FW=1",),
            "forced UF2": ("FORCE_UF2=1",),
            "default BLE DFU": ("DEFAULT_TO_OTA_DFU=1",),
            "debug": ("DEBUG=1",),
            "USB timeout": ("DFU_USB_ENUMERATION_TIMEOUT_MS=12345",),
            "mOTA RAM arena": ("MOTA_RAM_ARENA_SIZE=0",),
            "NFCT policy": ("USE_NFCT=yes",),
            "ANT key": ("ANT_LICENSE_KEY=profile-test-key",),
            "compiler flags": ("CFLAGS=-DPROFILE_TEST_ONE",),
            "assembler flags": ("ASFLAGS=-DPROFILE_TEST_TWO",),
            "linker flags": ("LDFLAGS=-Wl,--gc-sections",),
            "libraries": ("LIBS=-lm",),
        }
        for label, variables in variants.items():
            with self.subTest(label=label):
                _, digest = self.profile(*variables)
                self.assertNotEqual(baseline, digest)

        _, signed_a = self.profile(
            "SIGNED_FW=1", "SIGNED_FW_QX=0x11", "SIGNED_FW_QY=0x22"
        )
        _, signed_b = self.profile(
            "SIGNED_FW=1", "SIGNED_FW_QX=0x12", "SIGNED_FW_QY=0x22"
        )
        self.assertNotEqual(signed_a, signed_b, "signing-key changes must invalidate")
        self.assertNotIn("0x12", stamp.read_text(encoding="ascii"))

        # Prove that the stamp participates in a real object rule without
        # needing an ARM compiler: the stub records and materializes outputs.
        self.profile()
        object_build = Path(self.make_variable("OBJECT_BUILD"))
        main_object = object_build / "src" / "main.o"
        self.make(str(main_object))
        self.assertEqual(1, len(self.compiler_events("compile")))
        self.make(str(main_object))
        self.assertEqual(1, len(self.compiler_events("compile")))

        timeout_profile = ("DFU_USB_ENUMERATION_TIMEOUT_MS=12345",)
        self.make(str(main_object), *timeout_profile)
        self.assertEqual(2, len(self.compiler_events("compile")))
        self.make(str(main_object), *timeout_profile)
        self.assertEqual(2, len(self.compiler_events("compile")))

        out_name = self.make_variable("OUT_NAME", *timeout_profile)
        linked_output = self.build / f"{out_name}.out"
        self.make(str(linked_output), *timeout_profile)
        self.assertEqual(1, len(self.compiler_events("link")))
        self.make(str(linked_output), *timeout_profile)
        self.assertEqual(1, len(self.compiler_events("link")))

        changed_link_profile = (
            "DFU_USB_ENUMERATION_TIMEOUT_MS=12345",
            "LDFLAGS=-Wl,--gc-sections",
        )
        self.make(str(linked_output), *changed_link_profile)
        self.assertEqual(2, len(self.compiler_events("link")))
        self.make(str(linked_output), *changed_link_profile)
        self.assertEqual(2, len(self.compiler_events("link")))

    def test_final_artifacts_track_external_binary_inputs(self) -> None:
        makefile = MAKEFILE.read_text(encoding="utf-8")
        expected_rules = (
            r"\$\(BUILD\)/\$\(OUT_NAME\)_mbr\.hex:.*\$\(MBR_HEX\).*tools/hexmerge\.py",
            r"update-\$\(OUT_NAME\)_mbr\.uf2:.*lib/uf2/utils/uf2conv\.py",
            r"\$\(MERGED_FILE\)\.hex:.*\$\(SD_HEX\).*tools/hexmerge\.py",
            r"\$\(MERGED_FILE\)\.zip:.*\$\(SD_HEX\)",
        )
        for rule in expected_rules:
            with self.subTest(rule=rule):
                self.assertRegex(makefile, rule)

    def test_make_defines_the_ram_arena_before_loading_the_linker_script(self) -> None:
        self.assertEqual("65536", self.make_variable("MOTA_RAM_ARENA_SIZE"))
        ldflags = self.make_variable("LDFLAGS")
        arena = "-Wl,--defsym=__mota_ram_arena_size__=65536"
        script = "-Wl,-T,linker/nrf52840.ld"
        self.assertIn(arena, ldflags)
        self.assertIn(script, ldflags)
        self.assertLess(
            ldflags.index(arena),
            ldflags.index(script),
            "GNU ld must see the arena symbol before evaluating DEFINED() in the script",
        )

        disabled = self.make_variable("LDFLAGS", "MOTA_RAM_ARENA_SIZE=0")
        self.assertNotIn("__mota_ram_arena_size__", disabled)

    def test_dual_bank_selection_is_visible_to_size_constrained_sources(self) -> None:
        self.assertNotIn("-DDUALBANK_FW=1", self.make_variable("CFLAGS"))
        self.assertIn(
            "-DDUALBANK_FW=1",
            self.make_variable("CFLAGS", "DUALBANK_FW=1"),
        )

        cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn(
            "target_compile_definitions(bootloader PUBLIC DUALBANK_FW=1)",
            cmake,
        )
        screen = (ROOT / "src" / "screen.c").read_text(encoding="utf-8")
        self.assertIn(
            "#if defined(SIGNED_FW) && defined(DUALBANK_FW)",
            screen,
        )

    def test_ci_uses_the_documented_corrected_qualification_lineage(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertRegex(
            workflow,
            rf"OTAFIX_QUALIFICATION_VERSION:\s*['\"]{QUALIFICATION_VERSION}['\"]",
        )
        self.assertEqual(
            4,
            workflow.count(
                "MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=$OTAFIX_QUALIFICATION_VERSION"
            ),
        )
        self.assertNotIn(
            "MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=0x02040401", workflow
        )

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        test_readme = (ROOT / "test" / "README.md").read_text(encoding="utf-8")
        self.assertIn(QUALIFICATION_VERSION, readme)
        self.assertIn(QUALIFICATION_VERSION, test_readme)

    def test_ci_pins_gcc_14_2_and_builds_the_tightest_profiles(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(2, workflow.count("release: '14.2.Rel1'"))
        self.assertIn('_build/signed-dualbank-$board', workflow)
        self.assertIn('cmake-build-signed-dualbank-$board', workflow)

        for build_file in (MAKEFILE, ROOT / "CMakeLists.txt"):
            with self.subTest(build_file=build_file.name):
                contents = build_file.read_text(encoding="utf-8")
                self.assertIn("-Oz", contents)
                self.assertNotIn("-fmerge-all-constants", contents)
                self.assertNotIn("-fipa-pta", contents)
                self.assertNotIn("-fno-ipa-modref", contents)


if __name__ == "__main__":
    unittest.main(verbosity=2)
