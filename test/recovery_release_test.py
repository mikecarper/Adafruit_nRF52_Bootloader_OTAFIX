#!/usr/bin/env python3
"""Recovery release packaging must reject mixed, damaged, or stale inputs."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
import zlib

from intelhex import IntelHex

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import build_recovery_release as release

TAG = "0.11.0-OTAFIX2.4.7"
VERSION = 0x020407FF


class RecoveryReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / "input"
        self.input.mkdir()
        board = self.root / "src/boards/gat562"
        board.mkdir(parents=True)
        (board / "board.cmake").write_text("set(DEVICE_NAME GAT562_DFU)\n")
        docs = self.root / "docs"
        docs.mkdir()
        for name in ("recovery-allow-all.md", "recovery-rak3401-hardware-20260912.md"):
            (docs / name).write_text("Recovery only.\n")
        patch = mock.patch.object(release, "ROOT", self.root)
        patch.start()
        self.addCleanup(patch.stop)
        raw = bytearray(b"\xff" * 0xA000)
        struct.pack_into("<II", raw, 0, 0x20030000, 0xF4101)
        marker = b"R_0x020407FF\0"
        raw[0x100:0x100+len(marker)] = marker
        struct.pack_into("<IIHHIII16sI", raw, len(raw)-76,
                         0x464D4C42, 0x31435243, 1, 44, 0xF4000, len(raw),
                         0x239A0029, b"GAT562_DFU", 0)
        struct.pack_into("<IIHHIHHIHHI", raw, len(raw)-32,
                         0x324D4C42, 0x54464F53, 2, 32, VERSION, 140,
                         0xB6, 0x26000, 1, 0, 0)
        struct.pack_into("<I", raw, len(raw)-36, zlib.crc32(raw))
        stem = f"R_gat562_bootloader-{TAG}"
        self.hex = self.input / (stem + "_s140_6.1.1.hex")
        self.zip = self.input / (stem + "_s140_6.1.1.zip")
        self.uf2 = self.input / ("update-" + stem + "_mbr.uf2")
        image = IntelHex()
        image.puts(0xF4000, bytes(raw))
        image.puts(0x1000, b"S" * 16)
        image.write_hex_file(str(self.hex))
        with zipfile.ZipFile(self.zip, "w") as archive:
            archive.writestr("sd_bl.bin", b"S" * 16 + raw)
            archive.writestr("sd_bl.dat", b"test-init")
            archive.writestr("manifest.json", json.dumps({"manifest": {
                "dfu_version": 0.5, "softdevice_bootloader": {
                    "bin_file": "sd_bl.bin", "dat_file": "sd_bl.dat",
                    "bl_size": len(raw), "sd_size": 16}}}))
        chunks = [(0xF4000+i, raw[i:i+256]) for i in range(0, len(raw), 256)]
        uicr = bytearray(b"\xff" * 256)
        struct.pack_into("<II", uicr, 0x14, 0xF4000, 0xFE000)
        chunks.append((0x10001000, uicr))
        uf2 = bytearray()
        for index, (addr, payload) in enumerate(chunks):
            block = bytearray(512)
            struct.pack_into("<8I", block, 0, 0x0A324655, 0x9E5D5157,
                             0x2000, addr, 256, index, len(chunks), 0xD663823C)
            block[32:288] = payload
            struct.pack_into("<I", block, 508, 0x0AB16F30)
            uf2.extend(block)
        self.uf2.write_bytes(uf2)

    def inspect(self):
        return release.inspect_profile(self.input, "gat562", TAG, VERSION)

    def test_checked_bundle_inventory_and_checksums(self):
        bundle = release.build(self.input, self.root / "out", TAG)
        with zipfile.ZipFile(bundle) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertTrue(manifest["recovery_only"])
            self.assertEqual(manifest["board_count"], 1)
            self.assertEqual(manifest["packed_bootloader_version"], "0x020407FF")
            self.assertFalse(any(name.endswith(".mota") for name in archive.namelist()))
            for line in archive.read("SHA256SUMS.txt").decode().splitlines():
                digest, name = line.split("  ")
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)

    def test_mistagged_binary_rejected(self):
        with self.assertRaisesRegex(ValueError, "version/layout"):
            release.inspect_profile(self.input, "gat562", TAG, VERSION-1)

    def test_crc_corruption_rejected(self):
        image = IntelHex(str(self.hex))
        image[0xF4200] ^= 1
        image.write_hex_file(str(self.hex))
        with self.assertRaisesRegex(ValueError, "CRC"):
            self.inspect()

    def test_mismatched_uf2_rejected(self):
        blob = bytearray(self.uf2.read_bytes())
        blob[32+128] ^= 1
        self.uf2.write_bytes(blob)
        with self.assertRaisesRegex(ValueError, "UF2 differs"):
            self.inspect()

    def test_mismatched_zip_rejected(self):
        with zipfile.ZipFile(self.zip) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        files["sd_bl.bin"] = b"X" + files["sd_bl.bin"][1:]
        with zipfile.ZipFile(self.zip, "w") as archive:
            for name, blob in files.items(): archive.writestr(name, blob)
        with self.assertRaisesRegex(ValueError, "SoftDevice differs"):
            self.inspect()

    def test_missing_profile_artifact_rejected(self):
        self.uf2.unlink()
        with self.assertRaisesRegex(ValueError, "expected one"):
            self.inspect()

    def test_stale_artifact_rejected(self):
        (self.input / "old-build.zip").write_bytes(b"old")
        with self.assertRaisesRegex(ValueError, "stale"):
            release.build(self.input, self.root / "out", TAG)


if __name__ == "__main__":
    unittest.main(verbosity=2)
