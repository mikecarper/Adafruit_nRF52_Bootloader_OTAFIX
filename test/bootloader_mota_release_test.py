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
import struct
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

    def test_gat562_field_kit_is_phone_driven_and_exact_target_only(self) -> None:
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
        text = field.recipe("2.4.5", "0.11.0-OTAFIX2.4.5", package)
        self.assertIn("target=D50D2D44", text)
        self.assertIn("name=GAT562_DFU", text)
        self.assertIn("STOP for `4631_DFU`", text)
        self.assertIn("remote GAT562 repeater", text)
        self.assertIn("The remote GAT562 is NOT connected by USB", text)
        self.assertIn("XIAO Full Companion", text)
        self.assertIn("second GAT562", text)
        self.assertIn("Neither source option stages", text)
        self.assertIn("XIAO's 2 MB external flash is not used", text)
        self.assertIn("Pull** beside MID `A1B2C3D4`", text)
        self.assertIn("ota bootloader install A1B2C3D4 0123456789ABCDEF", text)
        self.assertNotIn("--target-serial", text)

    def test_release_workflow_builds_phone_field_components(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "githubci.yml").read_text(
            encoding="ascii"
        )
        self.assertIn("repository: mikecarper/meshcore-open", workflow)
        self.assertIn(field.MESHCORE_OPEN_COMMIT, workflow)
        self.assertIn(field.MESHCORE_COMMIT, workflow)
        self.assertIn("flutter build apk", workflow)
        self.assertIn(field.XIAO_COMPANION_ZIP, workflow)
        self.assertIn(field.GAT562_SOURCE_ZIP, workflow)
        self.assertIn(field.GAT562_RECEIVER_ZIP, workflow)
        self.assertIn("tools/build_gat562_field_kit.py", workflow)

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

            apk = root / field.ANDROID_APK_NAME
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr(
                    "AndroidManifest.xml",
                    "com.meshcore.meshcore_open.otafixfield\0"
                    "MeshCore Open OTAFIX Field".encode("utf-16le"),
                )
                archive.writestr("classes.dex", b"dex")
                archive.writestr("lib/arm64-v8a/libapp.so", b"app")
                archive.writestr("lib/arm64-v8a/libflutter.so", b"flutter")

            def fake_full_companion(
                names: tuple[str, str, str],
                artifact_target: str,
                application_start: int,
                softdevice_id: int,
            ) -> dict[str, Path]:
                uf2_name, zip_name, capabilities_name = names
                firmware = b"\0".join(
                    (
                        b"v1.17.1-dev-51ce1f8f",
                        b"14518fc2-7e7a-4d84-8cae-6664b0234cf2",
                        b"2bfaa1ee-7030-459a-b65a-e7cfd5b09735",
                        b"acf38a51-dd58-4dce-917f-0b1135e41b1a",
                        b"Bluetooth mOTA source",
                    )
                )
                zip_path = root / zip_name
                with zipfile.ZipFile(zip_path, "w") as archive:
                    archive.writestr("firmware.bin", firmware)
                    archive.writestr("firmware.dat", b"test")
                    archive.writestr(
                        "manifest.json",
                        json.dumps(
                            {
                                "manifest": {
                                    "application": {
                                        "bin_file": "firmware.bin",
                                        "dat_file": "firmware.dat",
                                        "init_packet_data": {
                                            "softdevice_req": [softdevice_id]
                                        },
                                    }
                                }
                            }
                        ),
                    )
                padded = firmware + b"\xff" * (-len(firmware) % 256)
                total = len(padded) // 256
                uf2 = bytearray()
                for number in range(total):
                    block = bytearray(512)
                    struct.pack_into(
                        "<IIIIIIII",
                        block,
                        0,
                        0x0A324655,
                        0x9E5D5157,
                        0x2000,
                        application_start + number * 256,
                        256,
                        number,
                        total,
                        0xADA52840,
                    )
                    block[32:288] = padded[number * 256 : (number + 1) * 256]
                    struct.pack_into("<I", block, 508, 0x0AB16F30)
                    uf2.extend(block)
                uf2_path = root / uf2_name
                uf2_path.write_bytes(uf2)
                capabilities_path = root / capabilities_name
                capabilities_path.write_text(
                    json.dumps(
                        {
                            "artifact_target": artifact_target,
                            "verified": True,
                            "capabilities": [
                                "profile.full",
                                "companion.temp_radio",
                                "companion.ota_cli",
                                "companion.bluetooth",
                                "companion.ble_mota_source",
                            ],
                        }
                    ),
                    encoding="ascii",
                )
                return {
                    uf2_name: uf2_path,
                    zip_name: zip_path,
                    capabilities_name: capabilities_path,
                }

            xiao_paths = fake_full_companion(
                (
                    field.XIAO_COMPANION_UF2,
                    field.XIAO_COMPANION_ZIP,
                    field.XIAO_COMPANION_CAPABILITIES,
                ),
                "Xiao_nrf52_companion_radio_full",
                0x27000,
                291,
            )
            gat562_source_paths = fake_full_companion(
                (
                    field.GAT562_SOURCE_UF2,
                    field.GAT562_SOURCE_ZIP,
                    field.GAT562_SOURCE_CAPABILITIES,
                ),
                "GAT562_30S_Mesh_Kit_companion_radio_full",
                0x26000,
                182,
            )

            release_component_paths = {}
            release_component_hashes = {}
            for index, name in enumerate(
                field.MESHCORE_RELEASE_ASSET_SHA256, 1
            ):
                path = root / name
                path.write_bytes(f"component {index}".encode("ascii"))
                release_component_paths[name] = path
                release_component_hashes[name] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
            args = argparse.Namespace(
                release_dir=release_dir,
                android_apk=apk,
                xiao_companion_uf2=xiao_paths[field.XIAO_COMPANION_UF2],
                xiao_companion_zip=xiao_paths[field.XIAO_COMPANION_ZIP],
                xiao_companion_capabilities=xiao_paths[
                    field.XIAO_COMPANION_CAPABILITIES
                ],
                gat562_source_uf2=gat562_source_paths[field.GAT562_SOURCE_UF2],
                gat562_source_zip=gat562_source_paths[field.GAT562_SOURCE_ZIP],
                gat562_source_capabilities=gat562_source_paths[
                    field.GAT562_SOURCE_CAPABILITIES
                ],
                gat562_receiver_uf2=release_component_paths[
                    field.GAT562_RECEIVER_UF2
                ],
                gat562_receiver_zip=release_component_paths[
                    field.GAT562_RECEIVER_ZIP
                ],
                tag="0.11.0-OTAFIX2.4.5",
            )
            with (
                mock.patch.object(field, "parse_args", return_value=args),
                mock.patch.object(
                    field,
                    "MESHCORE_RELEASE_ASSET_SHA256",
                    release_component_hashes,
                ),
            ):
                self.assertEqual(field.main(), 0)

            kit = release_dir / "GAT562-OTAFIX-2.4.5-LoRa-field-kit.zip"
            prefix = "GAT562-OTAFIX-2.4.5-LoRa-field-kit/"
            with zipfile.ZipFile(kit) as archive:
                names = set(archive.namelist())
                self.assertIn(prefix + "README.txt", names)
                self.assertIn(prefix + "SHA256SUMS", names)
                self.assertIn(prefix + "FIELD-COMPONENTS.json", names)
                self.assertIn(prefix + f"mota/{package_name}", names)
                self.assertIn(
                    prefix + f"android/{field.ANDROID_APK_NAME}", names
                )
                self.assertIn(
                    prefix + f"companion/{field.XIAO_COMPANION_ZIP}", names
                )
                self.assertIn(
                    prefix + f"companion/{field.GAT562_SOURCE_ZIP}", names
                )
                self.assertIn(
                    prefix
                    + f"target-prerequisite/{field.GAT562_RECEIVER_ZIP}",
                    names,
                )
                self.assertNotIn(prefix + "run-gat562-lora-update.sh", names)
                components = json.loads(
                    archive.read(prefix + "FIELD-COMPONENTS.json")
                )
                self.assertEqual(
                    components["meshcore_open"]["commit"],
                    field.MESHCORE_OPEN_COMMIT,
                )
                self.assertFalse(
                    components["transfer_model"][
                        "source_external_storage_required"
                    ]
                )
                self.assertEqual(
                    components["transfer_model"]["source_bridge_buffer_bytes"],
                    256,
                )
            inner_path = release_dir / "GAT562-OTAFIX-2.4.5-LoRa-bundle.zip"
            inner_blob = inner_path.read_bytes()
            with zipfile.ZipFile(io.BytesIO(inner_blob)) as inner:
                inner_manifest = json.loads(inner.read("manifest.json"))
                self.assertEqual(inner_manifest["package_count"], 1)
                self.assertEqual(inner_manifest["packages"][0]["board"], "gat562")


if __name__ == "__main__":
    unittest.main(verbosity=2)
