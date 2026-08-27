#!/usr/bin/env python3
"""Host tests for the menu-driven OTAFIX updater."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "otafix_mota_update.py"
SPEC = importlib.util.spec_from_file_location("otafix_mota_update", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
updater = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = updater
SPEC.loader.exec_module(updater)


class VersionTests(unittest.TestCase):
    def test_release_is_newer_than_preview(self) -> None:
        preview = updater.parse_version("0.11.0-OTAFIX2.4.3-preview.7")
        release = updater.parse_version("0.11.0-OTAFIX2.4.3")
        self.assertLess(preview.order, release.order)
        self.assertEqual(release.label, "2.4.3")

    def test_embedded_device_version(self) -> None:
        version = updater.parse_version("> 0.11.0-OTAFIX2.4.2-dirty-test-v")
        self.assertEqual(version.order, (2, 4, 2, 255))


class ReplyTests(unittest.TestCase):
    def test_identity_and_confirmation(self) -> None:
        reply = (
            "BL board=239A0071 target=1150F50E name=TOWER_V2_OTA "
            "crc=EFFB4005 abi=3 caps=0A | staged:ready "
            "mid=298D0152 hash=4F7B79397DB006C1"
        )
        identity = updater.parse_identity(reply)
        self.assertEqual(identity.target_id, "1150F50E")
        self.assertEqual(identity.caps, 0x0A)
        self.assertEqual(
            updater.parse_staged(reply),
            ("298D0152", "4F7B79397DB006C1"),
        )

    def test_tower_profile_uses_storage_capability(self) -> None:
        manifest = {
            "packages": [
                {"target_id": "0x1150F50E", "board": "heltec_mesh_tower_v2"},
                {
                    "target_id": "0x1150F50E",
                    "board": "heltec_mesh_tower_v2_sdcard",
                },
            ]
        }
        internal = updater.NodeIdentity(
            "239A0071", "1150F50E", "TOWER_V2_OTA", "00000000", 3, 0x0A
        )
        sdcard = updater.NodeIdentity(
            "239A0071", "1150F50E", "TOWER_V2_OTA", "00000000", 3, 0x09
        )
        self.assertEqual(
            updater.select_package(manifest, internal)["board"],
            "heltec_mesh_tower_v2",
        )
        self.assertEqual(
            updater.select_package(manifest, sdcard)["board"],
            "heltec_mesh_tower_v2_sdcard",
        )

    def test_binary_contract_rejects_wrong_target(self) -> None:
        target_id = 0x1150F50E
        fw_version = 0x020403FF
        merkle_root = bytes.fromhex("298D0152")
        image_hash = bytes.fromhex(
            "4f7b79397db006c1" + "00" * 24
        )
        hardware_id = "NRF_BL_239A0071_TOWER_V2_OTA"
        blob = bytearray(updater.MOTA_SIZE)
        blob[:4] = b"mOTA"
        struct.pack_into("<I", blob, 4, len(blob))
        manifest = memoryview(blob)[updater.MOTA_HEADER_SIZE:]
        manifest[0:3] = bytes((3, 0x07, 0x12))
        struct.pack_into("<IIII", manifest, 3, target_id, fw_version, 0xA000, 0xA000)
        manifest[19] = 10
        manifest[20:24] = merkle_root
        manifest[24:56] = image_hash
        manifest[56] = 0
        manifest[57:89] = hardware_id.encode("ascii").ljust(32, b"\0")
        manifest[89:97] = bytes(8)
        manifest[97:129] = bytes.fromhex(updater.OFFICIAL_PUBLIC_KEY)
        package = {
            "target_id": "0x1150F50E",
            "firmware_version": "0x020403FF",
            "hardware_id": hardware_id,
            "merkle_root": merkle_root.hex().upper(),
            "image_sha256": image_hash.hex(),
        }
        identity = updater.NodeIdentity(
            "239A0071", "1150F50E", "TOWER_V2_OTA", "00000000", 3, 0x0A
        )
        release = updater.Release(
            "0.11.0-OTAFIX2.4.3",
            updater.parse_version("OTAFIX2.4.3"),
            "", "", "", "", "", "",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "update.mota"
            path.write_bytes(blob)
            updater.validate_package_contract(path, package, identity, release)
            struct.pack_into("<I", manifest, 3, 0xE6F5F03F)
            path.write_bytes(blob)
            with self.assertRaises(updater.UpdateError):
                updater.validate_package_contract(path, package, identity, release)


class EstimateTests(unittest.TestCase):
    def test_measured_direct_baseline(self) -> None:
        self.assertEqual(
            updater.estimate_update_seconds(500.0, 1, 5),
            (65, 100, 105, 190),
        )

    def test_bandwidth_and_hops_scale_estimate(self) -> None:
        direct = updater.estimate_update_seconds(500.0, 1, 5)
        relayed = updater.estimate_update_seconds(125.0, 3, 5)
        self.assertGreater(relayed[0], direct[0] * 9)
        self.assertLess(relayed[0], direct[0] * 11)


if __name__ == "__main__":
    unittest.main()
