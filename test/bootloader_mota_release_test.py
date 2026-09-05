#!/usr/bin/env python3
"""Regression tests for the qualified bootloader mOTA release inventory."""

from __future__ import annotations

import argparse
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "build_bootloader_mota_release.py"
SPEC = importlib.util.spec_from_file_location("build_bootloader_mota_release", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release
SPEC.loader.exec_module(release)
FIELD_SCRIPT = ROOT / "tools" / "build_gat562_field_kit.py"
FIELD_SPEC = importlib.util.spec_from_file_location(
    "build_gat562_field_kit", FIELD_SCRIPT
)
assert FIELD_SPEC is not None and FIELD_SPEC.loader is not None
field = importlib.util.module_from_spec(FIELD_SPEC)
sys.modules[FIELD_SPEC.name] = field
FIELD_SPEC.loader.exec_module(field)


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

    def test_gat562_field_kit_is_offline_and_exact_target_only(self) -> None:
        self.assertEqual(field.GAT562_BOARD, "gat562")
        self.assertEqual(field.GAT562_TARGET, "0xD50D2D44")
        self.assertEqual(field.GAT562_NAME, "GAT562_DFU")
        self.assertEqual(
            field.GAT562_HARDWARE_ID, "NRF_BL_239A0029_GAT562_DFU"
        )
        package = {
            "file": "update-gat562_bootloader-0.11.0-OTAFIX2.4.5.mota",
            "merkle_root": "A1B2C3D4",
            "image_sha256": "0123456789abcdef" * 4,
        }
        text = field.recipe(
            "2.4.5",
            "0.11.0-OTAFIX2.4.5",
            package,
            "GAT562-OTAFIX-2.4.5-LoRa-bundle.zip",
        )
        self.assertIn("target=D50D2D44", text)
        self.assertIn("name=GAT562_DFU", text)
        self.assertIn("STOP if the target reports 4631_DFU", text)
        self.assertIn("ota pull A1B2C3D4 flash", text)
        self.assertIn("ota bootloader install A1B2C3D4 0123456789ABCDEF", text)

        wrapper = field.wrapper(
            "GAT562-OTAFIX-2.4.5-LoRa-bundle.zip",
            "pyserial-3.5-py2.py3-none-any.whl",
        ).decode("ascii")
        self.assertIn("--release-bundle", wrapper)
        self.assertIn("--direct-serial", wrapper)
        self.assertIn(
            "--require-identity 239A0029,D50D2D44,GAT562_DFU,3,0A",
            wrapper,
        )
        self.assertIn("linux-aarch64/motatool", wrapper)

    def test_release_workflow_builds_both_linux_field_binaries(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "githubci.yml").read_text(
            encoding="ascii"
        )
        self.assertIn("aarch64-unknown-linux-gnu", workflow)
        self.assertIn(
            "Keep field binaries compatible with Raspberry Pi OS Bookworm",
            workflow,
        )
        self.assertRegex(
            workflow,
            re.compile(r"bootloader-mota:.*?runs-on: ubuntu-22\.04", re.DOTALL),
        )
        self.assertIn("pyserial==3.5", workflow)
        self.assertIn("tools/build_gat562_field_kit.py", workflow)
        self.assertIn(
            "sha256sum otafix_mota_update.py > otafix_mota_update.py.sha256",
            workflow,
        )
        self.assertNotIn(
            "sha256sum _mota-release/otafix_mota_update.py", workflow
        )

    def test_field_builder_emits_one_checked_gat562_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release_dir = root / "release"
            package_dir = release_dir / "mota"
            package_dir.mkdir(parents=True)
            package_name = (
                "update-gat562_bootloader-0.11.0-OTAFIX2.4.5.mota"
            )
            package_blob = b"mOTA" + bytes(41326)
            package = {
                "board": "gat562",
                "file": package_name,
                "size": len(package_blob),
                "sha256": hashlib.sha256(package_blob).hexdigest(),
                "target_id": "0xD50D2D44",
                "firmware_version": "0x020405FF",
                "hardware_id": "NRF_BL_239A0029_GAT562_DFU",
                "merkle_root": "A1B2C3D4",
                "image_sha256": "01" * 32,
                "codec": "full",
            }
            manifest = {
                "release": "OTAFIX 2.4.5",
                "tag": "0.11.0-OTAFIX2.4.5",
                "packed_bootloader_version": "0x020405FF",
                "signing_public_key": field.OFFICIAL_PUBLIC_KEY,
                "package_format": 3,
                "package_count": 1,
                "packages": [package],
            }
            (release_dir / "manifest.json").write_text(
                json.dumps(manifest), encoding="ascii"
            )
            (release_dir / "OTAFIX_MOTA_SIGNING_PUBLIC_KEY.txt").write_text(
                field.OFFICIAL_PUBLIC_KEY + "\n", encoding="ascii"
            )
            (package_dir / package_name).write_bytes(package_blob)
            updater = root / "otafix_mota_update.py"
            updater.write_text(
                "# --release-bundle --direct-serial\n", encoding="ascii"
            )

            def fake_elf(machine: int, name: str) -> Path:
                blob = bytearray(20)
                blob[:6] = b"\x7fELF\x02\x01"
                blob[18:20] = machine.to_bytes(2, "little")
                path = root / name
                path.write_bytes(blob)
                return path

            x86 = fake_elf(field.ELF_MACHINE_X86_64, "motatool-x86")
            arm = fake_elf(field.ELF_MACHINE_AARCH64, "motatool-arm")
            wheel = root / "pyserial-3.5-py2.py3-none-any.whl"
            wheel.write_bytes(b"test pyserial wheel")
            args = argparse.Namespace(
                release_dir=release_dir,
                motatool_x86_64=x86,
                motatool_aarch64=arm,
                pyserial_wheel=wheel,
                updater=updater,
                tag="0.11.0-OTAFIX2.4.5",
            )
            with (
                mock.patch.object(field, "parse_args", return_value=args),
                mock.patch.object(
                    field,
                    "PYSERIAL_35_SHA256",
                    hashlib.sha256(wheel.read_bytes()).hexdigest(),
                ),
            ):
                self.assertEqual(field.main(), 0)

            kit = release_dir / "GAT562-OTAFIX-2.4.5-LoRa-field-kit.zip"
            prefix = "GAT562-OTAFIX-2.4.5-LoRa-field-kit/"
            with zipfile.ZipFile(kit) as archive:
                names = set(archive.namelist())
                self.assertIn(prefix + "README.txt", names)
                self.assertIn(prefix + "SHA256SUMS", names)
                self.assertIn(prefix + f"mota/{package_name}", names)
                self.assertIn(prefix + "bin/linux-aarch64/motatool", names)
                wrapper_info = archive.getinfo(
                    prefix + "run-gat562-lora-update.sh"
                )
                self.assertNotEqual((wrapper_info.external_attr >> 16) & 0o111, 0)
                inner_blob = archive.read(
                    prefix + "GAT562-OTAFIX-2.4.5-LoRa-bundle.zip"
                )
            with zipfile.ZipFile(io.BytesIO(inner_blob)) as inner:
                inner_manifest = json.loads(inner.read("manifest.json"))
                self.assertEqual(inner_manifest["package_count"], 1)
                self.assertEqual(inner_manifest["packages"][0]["board"], "gat562")


if __name__ == "__main__":
    unittest.main(verbosity=2)
