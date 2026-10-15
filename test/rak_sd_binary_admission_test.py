#!/usr/bin/env python3
"""Optional actual-binary admission checks; never builds or flashes ARM code.

Set OTAFIX_RAK4631_BOOTLOADER_BIN to a linked, CRC-stamped 40960-byte raw
bootloader.bin. The ordinary host suite does not depend on local build output.
Both current SD-app-only and deployed pre-SD adaptive admission are compiled
from the real parser; test mutations never change the original candidate.
"""
from pathlib import Path
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

from rak_sd_store_test import BASE, IDENTITY, SD, SRC, TEST


class RakSdBinaryAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        candidate = os.environ.get("OTAFIX_RAK4631_BOOTLOADER_BIN")
        if not candidate:
            raise unittest.SkipTest("set OTAFIX_RAK4631_BOOTLOADER_BIN for actual linked-binary checks")
        cls.data = Path(candidate).read_bytes()
        if len(cls.data) != 40960:
            raise AssertionError("the candidate must be an exact 40960-byte raw bootloader image")
        cls.cc = os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc")
        if not cls.cc:
            raise unittest.SkipTest("a native C compiler is required")
        cls.temp = tempfile.TemporaryDirectory(prefix="rak-sd-binary-")
        cls.directory = Path(cls.temp.name)
        cls.binaries = {}
        flags = ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Wno-unused-parameter"]
        if os.name != "nt":
            flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
        try:
            for name, defines in (("current", BASE + SD + IDENTITY),
                                  ("deployed", BASE + IDENTITY)):
                output = cls.directory / name
                result = subprocess.run([cls.cc, *flags, *defines,
                    "-I", str(SRC), "-I", str(SRC / "detools"),
                    str(TEST / "rak_sd_binary_admission_test.c"),
                    str(SRC / "detools/detools.c"), str(SRC / "sha256.c"),
                    str(SRC / "usb/uf2/bootloader_image.c"), "-o", str(output)],
                    capture_output=True, text=True, timeout=60)
                if result.returncode:
                    raise AssertionError(result.stdout + result.stderr)
                cls.binaries[name] = output
        except BaseException:
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def offset(data, magic):
        matches = [offset for offset in range(0, len(data) - 15, 4)
                   if data[offset:offset + len(magic)] == magic]
        if len(matches) != 1:
            raise AssertionError(f"expected exactly one aligned {magic!r} marker, got {matches}")
        return matches[0]

    @staticmethod
    def repair_crc(data):
        offset = len(data) - 76 + 40
        struct.pack_into("<I", data, offset, 0)
        struct.pack_into("<I", data, offset, zlib.crc32(data))

    def check(self, data, expected_current, expected_deployed):
        path = self.directory / "candidate.bin"
        path.write_bytes(data)
        for name, expected in (("current", expected_current), ("deployed", expected_deployed)):
            with self.subTest(policy=name):
                result = subprocess.run([str(self.binaries[name]), str(path),
                    *map(str, expected)], capture_output=True, text=True, timeout=30)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_actual_candidate_is_admitted_by_both_policies(self):
        self.check(self.data, (1, 1, 1), (1, 1, 1))

    def test_whole_image_crc_and_board_identity_are_enforced(self):
        changed = bytearray(self.data)
        changed[128] ^= 1
        self.check(changed, (1, 0, 0), (1, 0, 0))
        for offset in (len(changed) - 76 + 20, len(changed) - 76 + 24):
            with self.subTest(offset=offset):
                changed = bytearray(self.data)
                changed[offset] ^= 1
                self.repair_crc(changed)
                self.check(changed, (1, 0, 0), (1, 0, 0))

    def test_new_policy_requires_exact_app_only_sd_record(self):
        sd = self.offset(self.data, b"MOTASDRA")
        for field in range(16):
            with self.subTest(field=field):
                changed = bytearray(self.data)
                changed[sd + field] ^= 1
                self.repair_crc(changed)
                self.check(changed, (0, 1, 0), (1, 1, 1))

    def test_new_policy_rejects_duplicate_sd_record(self):
        sd = self.offset(self.data, b"MOTASDRA")
        changed = bytearray(self.data)
        # Replacing code in a copy is intentional: this is parser admission,
        # not an executable/RF qualification of the mutated image.
        changed[0x100:0x110] = changed[sd:sd + 16]
        self.repair_crc(changed)
        self.check(changed, (0, 1, 0), (1, 1, 1))

    def test_legacy_ram_nor_and_primary_caps_remain_required(self):
        for magic, field in ((b"MOTARAMA", 12), (b"MOTASTOR", 12), (b"MOTABLDR", 12)):
            with self.subTest(marker=magic):
                changed = bytearray(self.data)
                changed[self.offset(changed, magic) + field] ^= 1
                self.repair_crc(changed)
                self.check(changed, (0, 1, 0), (0, 1, 0))


if __name__ == "__main__":
    unittest.main()
