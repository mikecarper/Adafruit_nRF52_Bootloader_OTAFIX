#!/usr/bin/env python3
"""Derive the packed boot version from a canonical OTAFIX tag."""

import argparse
import re
import sys


PATTERN = re.compile(
    r"^(?:v?[0-9]+\.[0-9]+\.[0-9]+-)?"
    r"OTAFIX(?P<major>[0-9]+)\.(?P<minor>[0-9]+)\.(?P<patch>[0-9]+)"
    r"(?:-preview\.(?P<preview>[0-9]+))?$"
)


def derive(text: str) -> int:
    match = PATTERN.fullmatch(text)
    if not match:
        raise ValueError("version is not an exact canonical [upstream-]OTAFIXX.Y.Z[-preview.N] tag")
    major, minor, patch = (int(match.group(name)) for name in
                           ("major", "minor", "patch"))
    preview_text = match.group("preview")
    preview = 0xFF if preview_text is None else int(preview_text)
    if any(component > 0xFF for component in (major, minor, patch)):
        raise ValueError("OTAFIX X/Y/Z components must fit one byte")
    if preview_text is not None and not 1 <= preview <= 0xFE:
        raise ValueError("preview N must be in 1..254; stable releases use 255")
    value = (major << 24) | (minor << 16) | (patch << 8) | preview
    if value in (0, 0xFFFFFFFF):
        raise ValueError("derived boot version must be nonzero and not all-ones")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("--hex", action="store_true")
    args = parser.parse_args()
    try:
        value = derive(args.version)
    except ValueError as exc:
        print(f"derive_otafix_version: {exc}: {args.version!r}", file=sys.stderr)
        return 2
    print(f"0x{value:08X}" if args.hex else value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
