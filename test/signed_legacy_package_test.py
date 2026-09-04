#!/usr/bin/env python3
"""Host tests for the modern-Python Legacy DFU signing wrapper."""

from __future__ import annotations

import binascii
import hashlib
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "generate_signed_legacy_dfu",
    ROOT / "tools" / "generate_signed_legacy_dfu.py",
)
assert SPEC is not None and SPEC.loader is not None
signer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = signer
SPEC.loader.exec_module(signer)


def coordinate_text(value: int) -> str:
    return ",".join(f"0x{byte:02x}" for byte in value.to_bytes(32, "big"))


def make_unsigned_package(path: Path, firmware: bytes) -> None:
    softdevice_req = [0xFFFE]
    init_base = struct.pack("<HHIH", 0x0052, 52840, 0xFFFFFFFF, 1)
    init_base += struct.pack("<H", softdevice_req[0])
    firmware_crc = binascii.crc_hqx(firmware, 0xFFFF)
    manifest = {
        "manifest": {
            "dfu_version": 0.5,
            "softdevice_bootloader": {
                "bin_file": "sd_bl.bin",
                "dat_file": "sd_bl.dat",
                "sd_size": len(firmware) - 0xA000,
                "bl_size": 0xA000,
                "init_packet_data": {
                    "application_version": 0xFFFFFFFF,
                    "device_revision": 52840,
                    "device_type": 0x0052,
                    "firmware_crc16": firmware_crc,
                    "softdevice_req": softdevice_req,
                },
            },
        }
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("sd_bl.dat", init_base + struct.pack("<H", firmware_crc))
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("sd_bl.bin", firmware)


class SignedPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        public = self.private_key.public_key().public_numbers()
        self.qx = coordinate_text(public.x)
        self.qy = coordinate_text(public.y)

    def test_key_is_bound_to_compiled_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            key_path = Path(temporary) / "signing.pem"
            key_path.write_bytes(
                self.private_key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            loaded = signer.load_signing_key(
                key_path,
                signer.parse_public_coordinate(self.qx, "Qx"),
                signer.parse_public_coordinate(self.qy, "Qy"),
            )
            self.assertEqual(
                loaded.private_numbers().private_value,
                self.private_key.private_numbers().private_value,
            )
            wrong_qx_bytes = bytearray(
                signer.parse_public_coordinate(self.qx, "Qx")
            )
            wrong_qx_bytes[0] ^= 1
            wrong_qx = ",".join(f"0x{byte:02x}" for byte in wrong_qx_bytes)
            with self.assertRaisesRegex(signer.PackageError, "does not match"):
                signer.load_signing_key(
                    key_path,
                    signer.parse_public_coordinate(wrong_qx, "Qx"),
                    signer.parse_public_coordinate(self.qy, "Qy"),
                )

    def test_upgrade_emits_verifiable_standard_v08_packet(self) -> None:
        firmware = bytes((index * 13 + 5) & 0xFF for index in range(0xA100))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            unsigned_path = directory / "unsigned.zip"
            signed_path = directory / "signed.zip"
            make_unsigned_package(unsigned_path, firmware)
            signer.upgrade_package(unsigned_path, signed_path, self.private_key)

            with zipfile.ZipFile(signed_path) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {"manifest.json", "sd_bl.dat", "sd_bl.bin"},
                )
                manifest = json.loads(archive.read("manifest.json"))
                init_packet = archive.read("sd_bl.dat")
                self.assertEqual(archive.read("sd_bl.bin"), firmware)

        self.assertEqual(manifest["manifest"]["dfu_version"], 0.8)
        item = manifest["manifest"]["softdevice_bootloader"]
        metadata = item["init_packet_data"]
        base_length = 12
        self.assertEqual(len(init_packet), base_length + 104)
        ext_id, image_length = struct.unpack_from("<II", init_packet, base_length)
        firmware_hash = init_packet[base_length + 8 : base_length + 40]
        signature = init_packet[base_length + 40 : base_length + 104]
        self.assertEqual(ext_id, 2)
        self.assertEqual(image_length, len(firmware))
        self.assertEqual(firmware_hash, hashlib.sha256(firmware).digest())
        self.assertEqual(metadata["firmware_hash"], firmware_hash.hex())
        self.assertEqual(metadata["init_packet_ecds"], signature.hex())

        r = int.from_bytes(signature[:32], "big")
        s = int.from_bytes(signature[32:], "big")
        der_signature = encode_dss_signature(r, s)
        signed_prefix = init_packet[: base_length + 40]
        self.private_key.public_key().verify(
            der_signature, signed_prefix, ec.ECDSA(hashes.SHA256())
        )
        with self.assertRaises(InvalidSignature):
            self.private_key.public_key().verify(
                der_signature,
                bytes((signed_prefix[0] ^ 1,)) + signed_prefix[1:],
                ec.ECDSA(hashes.SHA256()),
            )


if __name__ == "__main__":
    unittest.main()
