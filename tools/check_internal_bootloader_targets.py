#!/usr/bin/env python3
"""Validate the internal-flash bootloader-update target inventory."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOARDS = ROOT / "src" / "boards"


def cmake_value(text: str, key: str) -> str | None:
    match = re.search(rf"set\(\s*{re.escape(key)}\s+([^\s\)]+)", text)
    return match.group(1) if match else None


def define_hex(text: str, key: str) -> int:
    match = re.search(rf"^\s*#define\s+{re.escape(key)}\s+(0x[0-9A-Fa-f]+)", text, re.MULTILINE)
    if not match:
        raise ValueError(f"missing {key}")
    return int(match.group(1), 16)


def main() -> int:
    targets: dict[int, str] = {}
    enabled = 0

    for board_dir in sorted(path for path in BOARDS.iterdir() if path.is_dir()):
        cmake_path = board_dir / "board.cmake"
        make_path = board_dir / "board.mk"
        if not cmake_path.exists() or not make_path.exists():
            continue

        cmake = cmake_path.read_text(encoding="utf-8")
        make = make_path.read_text(encoding="utf-8")
        is_nrf52840 = cmake_value(cmake, "MCU_VARIANT") == "nrf52840"
        external = cmake_value(cmake, "MOTA_QSPI_FLASH") == "ON" or cmake_value(cmake, "MOTA_SD_CARD") == "ON"
        internal = cmake_value(cmake, "MOTA_INTERNAL_BOOTLOADER_UPDATE") == "ON"

        if internal and (not is_nrf52840 or external):
            raise ValueError(f"{board_dir.name}: unsafe internal bootloader-update geometry")
        if is_nrf52840 and not external and not internal:
            raise ValueError(f"{board_dir.name}: internal-only nRF52840 target is not enabled")
        if not internal:
            continue
        if "-DMOTA_INTERNAL_BOOTLOADER_UPDATE=1" not in make:
            raise ValueError(f"{board_dir.name}: Make/CMake internal-update flags disagree")

        name = cmake_value(cmake, "DEVICE_NAME")
        if (name is None or not 1 <= len(name) <= 15 or not name.isascii() or
                any(ord(char) < 0x21 or ord(char) > 0x7E for char in name)):
            raise ValueError(f"{board_dir.name}: DEVICE_NAME is not canonical printable ASCII")
        board_h = (board_dir / "board.h").read_text(encoding="utf-8")
        board_id = (define_hex(board_h, "USB_DESC_VID") << 16) | define_hex(board_h, "USB_DESC_UF2_PID")
        if board_id in (0, 0xFFFFFFFF):
            raise ValueError(f"{board_dir.name}: invalid manifest board ID")

        hw_id = f"NRF_BL_{board_id:08X}_{name}".encode("ascii").ljust(32, b"\0")
        if len(hw_id) != 32:
            raise ValueError(f"{board_dir.name}: canonical hardware ID exceeds 32 bytes")
        target = int.from_bytes(hashlib.sha256(hw_id).digest()[:4], "little")
        if target in (0, 0xFFFFFFFF):
            raise ValueError(f"{board_dir.name}: invalid derived target ID")
        if target in targets:
            raise ValueError(f"target collision: {board_dir.name} and {targets[target]} both use {target:08X}")
        targets[target] = board_dir.name
        enabled += 1
        print(f"{board_dir.name:44} {target:08X} {hw_id.rstrip(bytes([0])).decode('ascii')}")

    if enabled == 0:
        raise ValueError("no internal bootloader-update targets found")
    print(f"internal bootloader target inventory: {enabled} unique targets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
