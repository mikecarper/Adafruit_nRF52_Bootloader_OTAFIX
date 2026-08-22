#!/usr/bin/env python3

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LINKERS = [
    ROOT / "linker" / name
    for name in (
        "nrf52.ld",
        "nrf52_debug.ld",
        "nrf52833.ld",
        "nrf52833_debug.ld",
        "nrf52840.ld",
        "nrf52840_debug.ld",
    )
]


class PeerDataLinkerTest(unittest.TestCase):
    def test_gnu_storage_is_one_ordered_record(self):
        source = (ROOT / "src" / "dfu_ble_svc.c").read_text()
        self.assertRegex(
            source,
            r'__attribute__\s*\(\(section\("\.noinit\.peer_data"\)\)\)\s*static\s+'
            r"dfu_ble_retained_peer_data_t\s+m_retained_peer_data\s*;",
        )
        self.assertIn("#define m_peer_data     m_retained_peer_data.peer_data", source)
        self.assertIn("#define m_peer_data_crc m_retained_peer_data.crc", source)

    def test_every_nrf52_linker_pins_the_writer_abi(self):
        for path in LINKERS:
            with self.subTest(linker=path.name):
                text = path.read_text()
                region = re.search(
                    r"NOINIT\s*\([^)]*\)\s*:\s*ORIGIN\s*=\s*(0x[0-9A-Fa-f]+)\s*,\s*LENGTH\s*=\s*(0x[0-9A-Fa-f]+)",
                    text,
                )
                self.assertIsNotNone(region)
                self.assertEqual(int(region.group(1), 16), 0x20007F80)
                self.assertGreaterEqual(int(region.group(2), 16), 62)

                section = re.search(r"\.noinit\s*\(NOLOAD\)\s*:\s*\{(.*?)\}\s*>\s*NOINIT", text, re.S)
                self.assertIsNotNone(section)
                body = section.group(1)
                ordered = (
                    "__dfu_peer_data_start__ = .;",
                    "KEEP(*(.noinit.peer_data))",
                    "__dfu_peer_data_end__ = .;",
                    "*(.noinit)",
                    "*(.noinit.*)",
                )
                positions = [body.find(token) for token in ordered]
                self.assertNotIn(-1, positions)
                self.assertEqual(positions, sorted(positions))

                self.assertRegex(
                    text,
                    r"ASSERT\s*\(\s*__dfu_peer_data_start__\s*==\s*ORIGIN\s*\(\s*NOINIT\s*\)",
                )
                self.assertRegex(
                    text,
                    r"ASSERT\s*\(\s*__dfu_peer_data_end__\s*-\s*__dfu_peer_data_start__\s*==\s*62",
                )


if __name__ == "__main__":
    unittest.main()
