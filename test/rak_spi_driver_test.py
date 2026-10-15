#!/usr/bin/env python3
"""Native mock tests for the production RAK shared-SPIM2 NOR/SD drivers.

These test real driver bodies, not OTA_DELTA_HOST_TEST media stubs. They do
not qualify electrical timing, SD hardware, or Nordic EasyDMA on a device.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TEST = ROOT / "test"


class RakSpiDriverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = os.environ.get("CC") or shutil.which("cc")
        cxx = os.environ.get("CXX") or shutil.which("c++")
        if not cc or not cxx:
            raise unittest.SkipTest("native C and C++ compilers are required")
        cls.temp = tempfile.TemporaryDirectory(prefix="rak-spi-driver-")
        cls.directory = Path(cls.temp.name)
        cls.binaries = {}
        flags = ["-O1", "-g", "-Wall", "-Wextra", "-Wno-unused-parameter"]
        if os.name != "nt":
            flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
        fixtures = {
            "nor": (cc, ["-std=c11", "-DMOTA_QSPI_FLASH=1", "-DMOTA_RAK_AUTO_STORE=1"], "rak_spi_nor_test.c"),
            # The register-hook fixture uses C++ assignment operators to model
            # TASKS_START. -fpermissive only permits C void* conversions in the
            # unmodified production C source included by that fixture.
            "transport": (cxx, ["-std=c++17", "-fpermissive", "-DMOTA_SD_CARD=1"], "rak_spi_transport_test.cpp"),
        }
        try:
            for name, (compiler, extra, source) in fixtures.items():
                binary = cls.directory / name
                result = subprocess.run([compiler, *flags, *extra,
                    "-DMOTA_RAK_SD_STORE=1", "-I", str(TEST / "rak_spi_stubs"),
                    "-I", str(ROOT / "src"), str(TEST / source), "-o", str(binary)],
                    capture_output=True, text=True, timeout=60)
                if result.returncode:
                    raise AssertionError(name + "\n" + result.stdout + result.stderr)
                cls.binaries[name] = binary
        except BaseException:
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_case(self, fixture, scenario):
        result = subprocess.run([str(self.binaries[fixture]), str(scenario)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_nor_explicit_pin_selectors_wake_jedec_and_idle_sleep(self): self.run_case("nor", 0)
    def test_nor_wrong_jedec_rejected(self): self.run_case("nor", 1)
    def test_nor_read_alignment_capacity_and_canaries(self): self.run_case("nor", 2)
    def test_nor_approval_only_changes_four_requested_bytes(self): self.run_case("nor", 3)
    def test_nor_rejects_arbitrary_writes_and_zero_to_one_programming(self): self.run_case("nor", 4)
    def test_nor_init_busy_timeout_is_bounded_and_never_sleeps_busy_part(self): self.run_case("nor", 5)
    def test_nor_requires_write_enable_latch(self): self.run_case("nor", 6)
    def test_nor_program_busy_timeout_keeps_chip_select_safe(self): self.run_case("nor", 7)
    def test_nor_readback_error_is_reported(self): self.run_case("nor", 8)
    def test_nor_transport_failures_cannot_program_or_sleep(self): self.run_case("nor", 9)
    def test_transport_pin_idle_levels_high_drive_and_frequency(self): self.run_case("transport", 0)
    def test_transport_dma_chunks_and_memory_barriers(self): self.run_case("transport", 1)
    def test_transport_read_only_write_only_and_empty_dma(self): self.run_case("transport", 2)
    def test_transport_timeout_stops_dma_and_latches_failure(self): self.run_case("transport", 3)
    def test_transport_release_pin_ownership_and_busy_cs_hold(self): self.run_case("transport", 4)
    def test_transport_single_byte_and_failed_byte(self): self.run_case("transport", 5)
    def test_sd_missing_card_deselects_other_nor_and_releases_bus(self): self.run_case("transport", 6)
    def test_transport_rejects_p1_pins_before_any_gpio_or_clock(self): self.run_case("transport", 7)
    def test_sd_command_dma_preserves_opcode_big_endian_argument_and_crc(self): self.run_case("transport", 8)


if __name__ == "__main__":
    unittest.main()
