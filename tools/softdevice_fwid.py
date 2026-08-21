#!/usr/bin/env python3
"""Read the exact little-endian FWID from a Nordic SoftDevice Intel HEX."""

import argparse
from pathlib import Path
import sys


SD_SIZE_ADDRESS = 0x3008
FWID_ADDRESS = 0x300C  # MBR base 0 + SOFTDEVICE_INFO_STRUCT_OFFSET 0x3000 + 0x0c


def load_ihex(path: Path) -> dict[int, int]:
    image: dict[int, int] = {}
    upper = 0
    for line_number, line in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        if not line.startswith(":"):
            raise ValueError(f"line {line_number}: not Intel HEX")
        raw = bytes.fromhex(line[1:])
        size, address, kind = raw[0], int.from_bytes(raw[1:3], "big"), raw[3]
        data = raw[4:4 + size]
        if len(raw) != size + 5 or (sum(raw) & 0xFF) != 0:
            raise ValueError(f"line {line_number}: invalid length/checksum")
        if kind == 0:
            for offset, value in enumerate(data):
                image[upper + address + offset] = value
        elif kind == 2:
            upper = int.from_bytes(data, "big") << 4
        elif kind == 4:
            upper = int.from_bytes(data, "big") << 16
    return image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("hex_file", type=Path)
    parser.add_argument("--app-base", action="store_true",
                        help="print the SoftDevice size/application base instead")
    args = parser.parse_args()
    try:
        image = load_ihex(args.hex_file)
        if args.app_base:
            value = sum(image[SD_SIZE_ADDRESS + i] << (8 * i) for i in range(4))
            if value == 0 or value == 0xFFFFFFFF or value & 0xFFF:
                raise ValueError(f"invalid app base 0x{value:08X}")
        else:
            value = image[FWID_ADDRESS] | (image[FWID_ADDRESS + 1] << 8)
            if value in (0, 0xFFFF):
                raise ValueError(f"invalid FWID 0x{value:04X}")
    except (OSError, ValueError, KeyError) as exc:
        print(f"softdevice_fwid: {exc}", file=sys.stderr)
        return 2
    print(f"0x{value:08X}" if args.app_base else f"0x{value:04X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
