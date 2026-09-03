#!/usr/bin/env python3
"""Regression tests for the qualified bootloader mOTA release inventory."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import re
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "build_bootloader_mota_release.py"
SPEC = importlib.util.spec_from_file_location("build_bootloader_mota_release", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release
SPEC.loader.exec_module(release)


def cmake_value(text: str, key: str) -> str:
    match = re.search(rf"set\(\s*{re.escape(key)}\s+([^\s\)]+)", text)
    if match is None:
        raise AssertionError(f"missing CMake value {key}")
    return match.group(1)


def define_hex(text: str, key: str) -> int:
    match = re.search(
        rf"^\s*#define\s+{re.escape(key)}\s+(0x[0-9A-Fa-f]+)",
        text,
        re.MULTILINE,
    )
    if match is None:
        raise AssertionError(f"missing C define {key}")
    return int(match.group(1), 16)


class QualifiedReleaseInventoryTest(unittest.TestCase):
    def test_inventory_has_seventeen_unique_profiles(self) -> None:
        self.assertEqual(len(release.QUALIFIED_BOARDS), 17)
        self.assertEqual(len(set(release.QUALIFIED_BOARDS)), 17)

    def test_gat562_exact_internal_profile_is_qualified(self) -> None:
        self.assertIn("gat562", release.QUALIFIED_BOARDS)

        board_dir = ROOT / "src" / "boards" / "gat562"
        cmake = (board_dir / "board.cmake").read_text(encoding="ascii")
        make = (board_dir / "board.mk").read_text(encoding="ascii")
        header = (board_dir / "board.h").read_text(encoding="ascii")

        self.assertEqual(cmake_value(cmake, "MCU_VARIANT"), "nrf52840")
        self.assertEqual(cmake_value(cmake, "DEVICE_NAME"), "GAT562_DFU")
        self.assertEqual(
            cmake_value(cmake, "MOTA_INTERNAL_BOOTLOADER_UPDATE"), "ON"
        )
        self.assertIn("-DDEVICE_NAME='\"GAT562_DFU\"'", make)
        self.assertIn("-DMOTA_INTERNAL_BOOTLOADER_UPDATE=1", make)

        board_id = (
            define_hex(header, "USB_DESC_VID") << 16
        ) | define_hex(header, "USB_DESC_UF2_PID")
        self.assertEqual(board_id, 0x239A0029)

        hardware_id = b"NRF_BL_239A0029_GAT562_DFU".ljust(32, b"\0")
        target_id = int.from_bytes(
            hashlib.sha256(hardware_id).digest()[:4], "little"
        )
        self.assertEqual(target_id, 0xD50D2D44)

        softdevice = (
            ROOT
            / "lib"
            / "softdevice"
            / "s140_nrf52_6.1.1"
            / "s140_nrf52_6.1.1_softdevice.hex"
        )
        reader = ROOT / "tools" / "softdevice_fwid.py"
        fwid = subprocess.run(
            [sys.executable, str(reader), str(softdevice)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        app_base = subprocess.run(
            [sys.executable, str(reader), str(softdevice), "--app-base"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(fwid, "0x00B6")
        self.assertEqual(app_base, "0x00026000")

    def test_workflow_and_signing_guide_pin_the_same_motatool(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "githubci.yml").read_text(
            encoding="ascii"
        )
        guide = (ROOT / "docs" / "mota_signing.md").read_text(encoding="ascii")
        workflow_pin = re.search(
            r"repository: mikecarper/motatool\s+ref: ([0-9a-f]{40})",
            workflow,
        )
        guide_pin = re.search(r"git checkout ([0-9a-f]{40})", guide)
        self.assertIsNotNone(workflow_pin)
        self.assertIsNotNone(guide_pin)
        self.assertEqual(workflow_pin.group(1), guide_pin.group(1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
