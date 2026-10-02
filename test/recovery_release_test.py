#!/usr/bin/env python3
"""Recovery release packaging must reject mixed, damaged, or stale inputs."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
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
            expected_crc = release.verify_manifest(str(self.hex))
            self.assertEqual(manifest["boards"][0]["bootloader_manifest_crc32"],
                             f"0x{expected_crc:08X}")
            self.assertFalse(any(name.endswith(".mota") for name in archive.namelist()))
            for line in archive.read("SHA256SUMS.txt").decode().splitlines():
                digest, name = line.split("  ")
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)

    def test_pending_source_port_is_excluded_from_recovery_bundle(self):
        pending = self.root / "src/boards/pending_test_board"
        pending.mkdir()
        (pending / "board.cmake").write_text("set(OTAFIX_BOARD_QUALIFICATION_PENDING ON)\n")
        bundle = release.build(self.input, self.root / "out", TAG)
        with zipfile.ZipFile(bundle) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["board_count"], 1)
            self.assertFalse(any("pending_test_board" in name for name in archive.namelist()))

    def test_retired_tower_excluded_from_normal_release_recovery(self):
        retired = self.root / "src/boards/heltec_mesh_tower_v2"
        retired.mkdir()
        (retired / "board.cmake").write_text("set(DEVICE_NAME TOWER_V2_OTA)\n")
        bundle = release.build(self.input, self.root / "out", TAG)
        with zipfile.ZipFile(bundle) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["board_count"], 1)
            self.assertFalse(any("heltec_mesh_tower_v2" in name for name in archive.namelist()))

    def test_mistagged_binary_rejected(self):
        with self.assertRaisesRegex(ValueError, "version/layout"):
            release.inspect_profile(self.input, "gat562", TAG, VERSION-1)

    def test_compile_only_port_is_excluded_even_from_all_board_bundle(self):
        pending = self.root / "src/boards/thinknode_m8"
        pending.mkdir()
        (pending / "board.cmake").write_text("set(OTAFIX_BOARD_QUALIFICATION_PENDING ON)\n")
        bundle = release.build(self.input, self.root / "out", TAG, include_pending=True)
        with zipfile.ZipFile(bundle) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["board_count"], 1)
            self.assertEqual(manifest["qualification_pending_boards"], [])
            self.assertIn("thinknode_m8", manifest["excluded_boards"])
            self.assertFalse(any("thinknode_m8" in name for name in archive.namelist()))

    def test_all_board_bundle_requires_pending_profile_artifacts(self):
        pending = self.root / "src/boards/pending_test_board"
        pending.mkdir()
        (pending / "board.cmake").write_text("set(OTAFIX_BOARD_QUALIFICATION_PENDING ON)\n")
        with self.assertRaisesRegex(ValueError, "pending_test_board: expected one"):
            release.build(self.input, self.root / "out", TAG, include_pending=True)

    def test_all_board_bundle_identifies_pending_profiles(self):
        pending = self.root / "src/boards/pending_test_board"
        pending.mkdir()
        (pending / "board.cmake").write_text(
            "set(OTAFIX_BOARD_QUALIFICATION_PENDING ON)\nset(DEVICE_NAME GAT562_DFU)\n")
        for path in (self.hex, self.zip, self.uf2):
            (self.input / path.name.replace("gat562", "pending_test_board")).write_bytes(
                path.read_bytes())
        bundle = release.build(self.input, self.root / "out", TAG, include_pending=True)
        with zipfile.ZipFile(bundle) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["board_count"], 2)
            self.assertEqual(manifest["qualification_pending_boards"], ["pending_test_board"])
            self.assertTrue(any(name.startswith("boards/pending_test_board/")
                                for name in archive.namelist()))

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

    def repaired_source_files(self):
        originals = {path.name: path.read_bytes() for path in self.input.iterdir()}
        for path in list(self.input.iterdir()):
            path.rename(path.with_name(path.name.replace("_bootloader-" + TAG, "_bootloader-v" + TAG)))
        return originals

    def repair_provenance(self):
        return {"source_tag": "R_v" + TAG, "source_commit": "1" * 40,
                "distribution_tag": "R_" + TAG, "distribution_tag_object": "2" * 40,
                "distribution_tag_commit": "3" * 40}

    def test_source_only_repair_preserves_asset_names_and_bytes_and_records_provenance_without_mota(self):
        originals = self.repaired_source_files()
        with mock.patch.object(release, "validate_provenance", return_value=self.repair_provenance()) as check:
            bundle = release.build(self.input, self.root / "out", TAG,
                                   source_tag="R_v" + TAG, release_tag="R_" + TAG)
        check.assert_called_once_with(self.root, "R_v" + TAG, "R_" + TAG)
        self.assertEqual({path.name: path.read_bytes() for path in self.input.iterdir()}, originals)
        with zipfile.ZipFile(bundle) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            for field, expected in self.repair_provenance().items():
                self.assertEqual(manifest[field], expected)
            self.assertNotIn("recovery_mota", manifest)
            self.assertEqual(set(manifest["boards"][0]["files"]), set(originals))
            for name, data in originals.items():
                self.assertEqual(archive.read("boards/gat562/" + name), data)
                self.assertEqual(manifest["boards"][0]["files"][name], hashlib.sha256(data).hexdigest())

    def test_alias_collision_is_rejected_without_changing_either_file(self):
        originals = self.repaired_source_files()
        paths = sorted(self.input.iterdir())
        collision = paths[0].with_name(paths[0].name.replace("_bootloader-v" + TAG, "_bootloader-" + TAG))
        collision.write_bytes(b"original distribution asset")
        before = {path.name: path.read_bytes() for path in self.input.iterdir()}
        with self.assertRaisesRegex(ValueError, "overwrite"):
            release.alias_plan(paths, "v" + TAG, TAG)
        self.assertEqual({path.name: path.read_bytes() for path in self.input.iterdir()}, before)
        self.assertIn(collision.name, originals)

    def test_bad_source_provenance_is_rejected_before_aliases_or_output(self):
        self.repaired_source_files()
        before = {path.name: path.read_bytes() for path in self.input.iterdir()}
        with mock.patch.object(release, "validate_provenance", side_effect=ValueError("different packed versions")):
            with self.assertRaisesRegex(ValueError, "different packed"):
                release.build(self.input, self.root / "out", TAG,
                              source_tag="R_v" + TAG, release_tag="R_" + TAG)
        self.assertEqual({path.name: path.read_bytes() for path in self.input.iterdir()}, before)
        self.assertFalse((self.root / "out").exists())

    def test_bad_source_artifact_is_rejected_before_any_alias(self):
        self.repaired_source_files()
        source_uf2 = next(self.input.glob("*.uf2"))
        blob = bytearray(source_uf2.read_bytes())
        blob[32 + 128] ^= 1
        source_uf2.write_bytes(blob)
        before = {path.name: path.read_bytes() for path in self.input.iterdir()}
        with mock.patch.object(release, "validate_provenance", return_value=self.repair_provenance()):
            with self.assertRaisesRegex(ValueError, "UF2 differs"):
                release.build(self.input, self.root / "out", TAG,
                              source_tag="R_v" + TAG, release_tag="R_" + TAG)
        self.assertEqual({path.name: path.read_bytes() for path in self.input.iterdir()}, before)

    def test_distribution_filename_version_must_match_release_tag(self):
        with self.assertRaisesRegex(ValueError, "external recovery filename version"):
            release.build(self.input, self.root / "out", TAG,
                          source_tag="R_v" + TAG, release_tag="R_v" + TAG)

    def test_real_clean_source_tag_repair_builds_without_moving_distribution_tag(self):
        originals = self.repaired_source_files()
        def git(*args):
            return subprocess.check_output(["git", "-C", str(self.root), *args],
                                           text=True, stderr=subprocess.PIPE).strip()
        git("init", "-q")
        git("config", "user.email", "test@example.invalid")
        git("config", "user.name", "Recovery packaging test")
        (self.root / ".gitignore").write_text("/input/\n/out/\n", encoding="ascii")
        git("add", ".")
        git("commit", "-qm", "Original distribution source")
        original_commit = git("rev-parse", "HEAD")
        git("tag", "-am", "Original distribution", "R_" + TAG)
        original_object = git("rev-parse", "refs/tags/R_" + TAG)
        (self.root / "correction.txt").write_text("Fixed source\n", encoding="ascii")
        git("add", "correction.txt")
        git("commit", "-qm", "Corrected source")
        source_commit = git("rev-parse", "HEAD")
        git("tag", "-am", "Source-only correction", "R_v" + TAG)
        bundle = release.build(self.input, self.root / "out", TAG,
                               source_tag="R_v" + TAG, release_tag="R_" + TAG)
        with zipfile.ZipFile(bundle) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["source_commit"], source_commit)
            self.assertEqual(manifest["distribution_tag_commit"], original_commit)
            self.assertEqual(manifest["distribution_tag_object"], original_object)
        self.assertEqual(git("rev-parse", "refs/tags/R_" + TAG), original_object)
        self.assertEqual(git("status", "--porcelain"), "")
        self.assertEqual({path.name: path.read_bytes() for path in self.input.iterdir()}, originals)


if __name__ == "__main__":
    unittest.main(verbosity=2)
