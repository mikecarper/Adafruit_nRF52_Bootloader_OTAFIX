#!/usr/bin/env python3
"""Compile production flash-cache and UF2 writers for manual update regressions."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ManualUf2IntegrityTest(unittest.TestCase):
    def run_host(self, source, *flags, stubs=None):
        with tempfile.TemporaryDirectory(prefix="otafix-manual-uf2-") as directory:
            temporary = Path(directory)
            for name, content in (stubs or {}).items():
                (temporary / name).write_text(content)
            binary = temporary / ("test.exe" if os.name == "nt" else "test")
            subprocess.run([
                os.environ.get("CC", "gcc"), "-std=c11", "-O2", "-Wall", "-Wextra",
                "-Werror", "-Wno-unused-parameter", "-Wno-int-to-pointer-cast",
                "-I", str(temporary), *flags, str(ROOT / "test" / source),
                "-o", str(binary),
            ], check=True)
            subprocess.run([str(binary)], check=True)

    def test_pending_and_committed_cache_matches(self):
        self.run_host("flash_cache_test.c", stubs={
            name: "#pragma once\n" for name in
            ("nrf_sdm.h", "nrf_wdt.h", "nrfx_nvmc.h", "boards.h", "dfu_types.h")
        })

    def test_uf2_bootloader_integrity(self):
        for profile in ([], ["-DMOTA_QSPI_BOOTLOADER_UPDATE"]):
            with self.subTest(profile=profile):
                self.run_host("uf2_volume_test.c", "-DNRF52840_XXAA", *profile,
                              "-I", str(ROOT / "test/uf2_stubs"),
                              "-I", str(ROOT / "test"), "-I", str(ROOT / "src"),
                              "-I", str(ROOT / "src/usb/uf2"))


if __name__ == "__main__":
    unittest.main()
