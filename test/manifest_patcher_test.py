#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import unittest

from intelhex import IntelHex


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "patch_bootloader_manifest.py"
SPEC = importlib.util.spec_from_file_location("patch_bootloader_manifest", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


IMAGE_START = 0xF4000
IMAGE_SIZE = 0xA000
FIXED_OFFSET = IMAGE_START + IMAGE_SIZE - (MODULE.HEADER_SIZE + MODULE.EXT_SIZE)


def envelope(address=FIXED_OFFSET):
    header = struct.pack(
        MODULE.HEADER_FORMAT,
        MODULE.MAGIC0,
        MODULE.MAGIC1,
        MODULE.VERSION,
        MODULE.HEADER_SIZE,
        IMAGE_START,
        IMAGE_SIZE,
        0x239A0071,
        b"TOWER_V2_OTA\0\0\0\0",
        0,
    )
    extension = struct.pack(
        MODULE.EXT_FORMAT,
        MODULE.EXT_MAGIC0,
        MODULE.EXT_MAGIC1,
        MODULE.EXT_VERSION,
        MODULE.EXT_SIZE,
        0x0204010D,
        140,
        0x00B6,
        0x26000,
        1,
        0,
        0,
    )
    image = IntelHex()
    for offset, value in enumerate(header + extension):
        image[address + offset] = value
    return image


class ManifestPatcherTest(unittest.TestCase):
    def test_fixed_final_envelope_is_accepted(self):
        address, start, size, name, _ = MODULE.find_manifest(envelope())
        self.assertEqual((address, start, size, name),
                         (FIXED_OFFSET, IMAGE_START, IMAGE_SIZE, "TOWER_V2_OTA"))

    def test_relocated_only_envelope_is_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.find_manifest(envelope(IMAGE_START + 0x9E00))

    def test_patched_crc_is_nonzero_and_independently_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bootloader.hex"
            envelope().write_hex_file(path)
            MODULE.patch_manifest(str(path))
            checksum = MODULE.verify_manifest(str(path))
            self.assertNotEqual(checksum, 0)
            damaged = IntelHex(str(path))
            damaged[IMAGE_START] = 0
            damaged.write_hex_file(path)
            with self.assertRaises(ValueError):
                MODULE.verify_manifest(str(path))

    def test_patch_canonicalizes_crlf_input_and_is_byte_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bootloader.hex"
            image = envelope()
            image.start_addr = {"EIP": IMAGE_START}
            image.write_hex_file(path, eolstyle="CRLF")
            self.assertIn(b"\r\n", path.read_bytes())
            MODULE.patch_manifest(str(path))
            first = path.read_bytes()
            self.assertNotIn(b"\r", first)
            self.assertTrue(first.endswith(b":00000001FF\n"))
            self.assertEqual(IntelHex(str(path)).start_addr, image.start_addr)
            MODULE.verify_manifest(str(path))
            MODULE.patch_manifest(str(path))
            self.assertEqual(path.read_bytes(), first)

    def test_cmake_flash_targets_use_only_the_patched_hex(self):
        cmake = (MODULE_PATH.parents[1] / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("COMMAND ${BOOTLOADER_VERIFY_COMMAND}", cmake)
        self.assertIn("COMMAND ${BOOTLOADER_MERGED_VERIFY_COMMAND}", cmake)
        self.assertIn("set(BOOTLOADER_ARTIFACT_NAME bootloader)", cmake)
        self.assertIn('set(BOOTLOADER_ARTIFACT_NAME "R_${BOARD}_bootloader")', cmake)
        self.assertNotIn("hexmerge.py --overlap=replace", cmake)
        for target in ("flash-bootloader", "flash-all"):
            match = re.search(
                rf"add_custom_target\({re.escape(target)}\n(.*?)\n  \)",
                cmake,
                re.DOTALL,
            )
            self.assertIsNotNone(match, target)
            block = match.group(1)
            self.assertIn("$<TARGET_FILE_DIR:bootloader>/${BOOTLOADER_ARTIFACT_NAME}.hex", block)
            self.assertNotIn("$<TARGET_FILE:bootloader>", block)

    def test_make_verifies_mbr_merge_without_overlap_replacement(self):
        makefile = (MODULE_PATH.parents[1] / "Makefile").read_text(encoding="utf-8")
        match = re.search(
            r"\$\(BUILD\)/\$\(OUT_NAME\)_mbr\.hex:.*?\n(.*?)(?=\n# Bootloader)",
            makefile,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        block = match.group(1)
        self.assertIn("tools/hexmerge.py -o $@ $<:0: $(MBR_HEX):0:", block)
        self.assertIn("tools/patch_bootloader_manifest.py $@ --verify", block)
        self.assertNotIn("--overlap=replace", block)

    def test_mbr_merge_discards_start_records_but_rejects_data_overlap(self):
        hexmerge = MODULE_PATH.parent / "hexmerge.py"
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            boot_path = directory / "bootloader.hex"
            mbr_path = directory / "mbr.hex"
            merged_path = directory / "bootloader_mbr.hex"

            boot = envelope()
            boot.start_addr = {"CS": 0xF000, "IP": 0xD47D}
            boot.write_hex_file(boot_path)
            MODULE.patch_manifest(str(boot_path))

            mbr = IntelHex()
            mbr[0] = 0x42
            mbr.start_addr = {"EIP": 0}
            mbr.write_hex_file(mbr_path)

            command = [
                sys.executable,
                str(hexmerge),
                "-o",
                str(merged_path),
                f"{boot_path}:0:",
                f"{mbr_path}:0:",
            ]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(b"\r", merged_path.read_bytes())
            self.assertTrue(merged_path.read_bytes().endswith(b":00000001FF\n"))
            self.assertEqual(IntelHex(str(merged_path))[0], 0x42)
            MODULE.verify_manifest(str(merged_path))

            mbr[FIXED_OFFSET] = 0
            mbr.write_hex_file(mbr_path)
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("overlap", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
