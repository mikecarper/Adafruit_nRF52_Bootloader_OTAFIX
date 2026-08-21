#!/usr/bin/env python3

import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "tools" / "otafix_cf2.py"
IMAGE_START = 0x000F4000
IMAGE_SIZE = 0x0000A000
CF2_OFFSET = 0x00009F50
MANIFEST_OFFSET = 0x00009FB4


def make_raw(protected=True):
    image = bytearray(b"\xFF" * IMAGE_SIZE)
    struct.pack_into("<II", image, 0, 0x20040000, IMAGE_START + 0x101)
    config = (
        0x1E9E10F1, 0x20227A79, 5, 100,
        204, 0x100000,
        205, 0x40000,
        208, 0x239A0071,
        209, 0xADA52840,
        210, 0x20,
        0, 0, 0, 0, 0, 0, 0, 0,
    )
    struct.pack_into("<" + "I" * len(config), image, CF2_OFFSET, *config)
    if protected:
        struct.pack_into(
            "<IIHHIII16sI",
            image,
            MANIFEST_OFFSET,
            0x464D4C42,
            0x31435243,
            1,
            44,
            IMAGE_START,
            IMAGE_SIZE,
            0x239A0071,
            b"TOWER_V2_OTA\0\0\0\0",
            0x12345678,
        )
        struct.pack_into("<II", image, MANIFEST_OFFSET + 44, 0x324D4C42, 0x54464F53)
    return bytes(image)


def make_uf2(raw):
    blocks = []
    count = len(raw) // 256
    for number in range(count):
        payload = raw[number * 256:(number + 1) * 256]
        block = bytearray(512)
        struct.pack_into(
            "<IIIIIIII",
            block,
            0,
            0x0A324655,
            0x9E5D5157,
            0x00002000,
            IMAGE_START + number * 256,
            256,
            number,
            count,
            0xADA52840,
        )
        block[32:32 + 256] = payload
        struct.pack_into("<I", block, 508, 0x0AB16F30)
        blocks.append(block)
    return b"".join(blocks)


class Cf2GuardTest(unittest.TestCase):
    def run_wrapper(self, *args):
        return subprocess.run(
            [sys.executable, str(WRAPPER), *map(str, args)],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_protected_bin_and_uf2_are_readable_but_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            config = directory / "change.cf2"
            config.write_text("FLASH_BYTES = 0x80000\n", encoding="ascii")
            for name, contents in (
                ("tower.bin", make_raw()),
                ("tower.uf2", make_uf2(make_raw())),
            ):
                image = directory / name
                image.write_bytes(contents)
                inspect = self.run_wrapper(image)
                self.assertEqual(inspect.returncode, 0, inspect.stderr)
                self.assertIn("Found CFG DATA", inspect.stdout)
                before = hashlib.sha256(image.read_bytes()).digest()
                patch = self.run_wrapper(image, config)
                self.assertEqual(patch.returncode, 2)
                self.assertIn("BLMF-protected", patch.stderr)
                self.assertEqual(hashlib.sha256(image.read_bytes()).digest(), before)

    def test_legacy_patch_is_transactional_and_fixes_node_fs_path(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            image = directory / "legacy.bin"
            image.write_bytes(make_raw(protected=False))
            config = directory / "change.cf2"
            config.write_text("FLASH_BYTES = 0x80000\n", encoding="ascii")
            result = self.run_wrapper(image, config)
            self.assertEqual(result.returncode, 0, result.stderr)
            inspect = self.run_wrapper(image)
            self.assertEqual(inspect.returncode, 0, inspect.stderr)
            self.assertIn("FLASH_BYTES = 0x80000", inspect.stdout)

    def test_legacy_patch_cannot_cross_existing_zero_padding(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            image = directory / "legacy.bin"
            contents = bytearray(make_raw(protected=False))
            # End the pre-existing CF2 zero span immediately after its required
            # terminator. The upstream patcher may alter its temporary copy,
            # but the wrapper must discard it before touching the source.
            sentinel = CF2_OFFSET + 16 + 5 * 8 + 8
            contents[sentinel:sentinel + 4] = b"STOP"
            image.write_bytes(contents)
            before = hashlib.sha256(contents).digest()
            config = directory / "grow.cf2"
            config.write_text(
                "FLASH_BYTES = 0x100000\n"
                "RAM_BYTES = 0x40000\n"
                "BOOTLOADER_BOARD_ID = 0x239A0071\n"
                "UF2_FAMILY = 0xADA52840\n"
                "PINS_PORT_SIZE = 0x20\n"
                "PIN_LED = 1\n",
                encoding="ascii",
            )
            result = self.run_wrapper(image, config)
            self.assertEqual(result.returncode, 2)
            self.assertIn("refusing unsafe patch", result.stderr)
            self.assertEqual(hashlib.sha256(image.read_bytes()).digest(), before)


if __name__ == "__main__":
    unittest.main()
