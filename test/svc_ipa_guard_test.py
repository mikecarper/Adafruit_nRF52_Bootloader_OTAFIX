#!/usr/bin/env python3
"""Keep GCC IPA from optimizing through Nordic SoftDevice SVC portals."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEADERS = [ROOT / "lib/softdevice/mbr/headers/nrf_svc.h"]
HEADERS.extend(sorted((ROOT / "lib/softdevice").glob("s*_nrf52_*/*_API/include/nrf_svc.h")))


def main() -> None:
    if len(HEADERS) != 5:
        raise AssertionError(f"expected five bundled SoftDevice SVC headers, found {len(HEADERS)}")

    required = (
        "__attribute__((noipa))",
        "__attribute__((naked))",
        "__attribute__((weak))",
        "__asm volatile(",
        '"r0", "memory"',
    )
    for header in HEADERS:
        source = header.read_text()
        missing = [token for token in required if token not in source]
        if missing:
            raise AssertionError(f"{header.relative_to(ROOT)} lacks {', '.join(missing)}")

    print("Nordic SVC GCC IPA barriers: PASS")


if __name__ == "__main__":
    main()
