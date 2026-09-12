#!/usr/bin/env python3
"""Shared board identity for Secure-only BLE qualification builds/packages.

This is a compatibility guard, not authentication. Keep the original RAK3401
lab ID; use the canonical board-name CRC32 for other targets (USB IDs collide).
"""
import argparse
from pathlib import Path
import re
import zlib

ROOT = Path(__file__).resolve().parents[1]


def hardware_version(board):
    if not re.fullmatch(r'[a-z0-9_]+', board) or not (ROOT / 'src/boards' / board / 'board.cmake').is_file():
        raise ValueError('unknown board')
    return 0x3401 if board == 'wiscore_rak3401' else zlib.crc32(board.encode('ascii'))


def target(board):
    from softdevice_fwid import load_ihex, FWID_ADDRESS, SD_SIZE_ADDRESS
    hw = hardware_version(board)
    config = (ROOT / 'src/boards' / board / 'board.cmake').read_text()
    if not re.search(r'set\(MCU_VARIANT\s+nrf52840\)', config):
        raise ValueError('Secure qualification currently supports nRF52840 only')
    version = re.search(r'set\(SD_VERSION\s+([\d.]+)\)', config)
    version = version[1] if version else '6.1.1'
    name = f's140_nrf52_{version}'
    image = load_ihex(ROOT / 'lib/softdevice' / name / (name + '_softdevice.hex'))
    word = lambda addr, size: sum(image[addr + i] << (i * 8) for i in range(size))
    return dict(hw_version=hw, fwid=word(FWID_ADDRESS, 2), app_base=word(SD_SIZE_ADDRESS, 4))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('board')
    parser.add_argument('--hw-version', action='store_true', required=True)
    args = parser.parse_args()
    try:
        print(f'0x{hardware_version(args.board):08X}')
    except ValueError as exc:
        parser.error(str(exc))
