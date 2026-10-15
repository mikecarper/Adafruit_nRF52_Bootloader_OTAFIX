#!/usr/bin/env python3
"""Check the exact RAK4631 SD inventory exception using isolated source trees."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_internal_bootloader_targets", ROOT / "tools/check_internal_bootloader_targets.py")
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)

HEADER = """#define USB_DESC_VID 0x239A
#define USB_DESC_UF2_PID 0x0029
"""


class InternalBootloaderTargetsTests(unittest.TestCase):
    def setUp(self):
        source = ROOT / "src/boards/wiscore_rak4631_auto"
        self.cmake = (source / "board.cmake").read_text(encoding="ascii")
        self.make = (source / "board.mk").read_text(encoding="ascii")

    def inventory(self, name="wiscore_rak4631_auto", cmake=None, make=None):
        with tempfile.TemporaryDirectory(prefix="otafix-target-inventory-") as folder:
            boards = Path(folder)
            board = boards / name
            board.mkdir()
            (board / "board.cmake").write_text(self.cmake if cmake is None else cmake)
            (board / "board.mk").write_text(self.make if make is None else make)
            (board / "board.h").write_text(HEADER)
            with mock.patch.object(checker, "BOARDS", boards), contextlib.redirect_stdout(io.StringIO()) as output:
                result = checker.main()
                return result, output.getvalue()

    def test_exact_combined_rak_keeps_legacy_target_identity(self):
        result, output = self.inventory()
        self.assertEqual(0, result)
        self.assertIn("NRF_BL_239A0029_4631_DFU", output)
        self.assertIn("1 profiles, 1 unique targets", output)
        # Removing only the additive SD extension models the historical image.
        sd_flags = ("RAK_SD_STORE", "SD_CARD")
        cmake, make = self.cmake, self.make
        for flag in sd_flags:
            cmake = cmake.replace(f"set(MOTA_{flag} ON)", "")
            make = make.replace(f"-DMOTA_{flag}=1", "")
        _, older = self.inventory(cmake=cmake, make=make)
        new_target = output.splitlines()[0].split()[1]
        self.assertEqual(new_target, older.splitlines()[0].split()[1])

    def test_each_required_flag_missing_in_either_build_is_rejected(self):
        for flag in ("RAK_SD_STORE", "RAK_AUTO_STORE", "QSPI_FLASH", "SD_CARD",
                     "INTERNAL_BOOTLOADER_UPDATE"):
            with self.subTest(flag=flag, build="CMake"):
                with self.assertRaises(ValueError):
                    self.inventory(cmake=self.cmake.replace(f"set(MOTA_{flag} ON)", ""))
            with self.subTest(flag=flag, build="Make"):
                with self.assertRaises(ValueError):
                    self.inventory(make=self.make.replace(f"-DMOTA_{flag}=1", ""))

    def test_exception_does_not_extend_to_rak3401_tower_or_other_boards(self):
        for board in ("wiscore_rak3401_auto", "heltec_mesh_tower_v2_sdcard", "other"):
            with self.subTest(board=board):
                with self.assertRaisesRegex(ValueError, "unsafe combined RAK"):
                    self.inventory(name=board)

    def test_zero_or_missing_arena_and_extra_backends_are_rejected(self):
        for cmake in (self.cmake.replace("MOTA_RAM_ARENA_SIZE 65536", "MOTA_RAM_ARENA_SIZE 0"),
                      self.cmake.replace("MOTA_RAM_ARENA_SIZE", "UNRELATED_ARENA"),
                      self.cmake.replace("nrf52840", "nrf52833"),
                      self.cmake + "\nset(MOTA_SD_DUAL_STORE ON)\n",
                      self.cmake + "\nset(MOTA_SD_BOOTLOADER_UPDATE ON)\n",
                      self.cmake + "\nset(MOTA_QSPI_BOOTLOADER_UPDATE ON)\n"):
            with self.subTest(cmake=cmake):
                with self.assertRaises(ValueError):
                    self.inventory(cmake=cmake)
        for make in (self.make.replace("MOTA_RAM_ARENA_SIZE ?= 65536", "MOTA_RAM_ARENA_SIZE ?= 0"),
                     self.make.replace("MOTA_RAM_ARENA_SIZE", "UNRELATED_ARENA"),
                     self.make + "\nCFLAGS += -DMOTA_SD_DUAL_STORE=1\n",
                     self.make + "\nCFLAGS += -DMOTA_SD_BOOTLOADER_UPDATE=1\n",
                     self.make + "\nCFLAGS += -DMOTA_QSPI_BOOTLOADER_UPDATE=1\n"):
            with self.subTest(make=make):
                with self.assertRaises(ValueError):
                    self.inventory(make=make)

    def test_commented_flags_cannot_grant_exception(self):
        with self.assertRaises(ValueError):
            self.inventory(cmake=self.cmake.replace("set(MOTA_SD_CARD ON)", "#set(MOTA_SD_CARD ON)"))
        with self.assertRaises(ValueError):
            self.inventory(make=self.make.replace("CFLAGS += -DMOTA_SD_CARD=1", "#CFLAGS += -DMOTA_SD_CARD=1"))

    def test_existing_rak3401_and_tower_profiles_are_unchanged(self):
        for board in ("wiscore_rak3401_auto", "heltec_mesh_tower_v2_sdcard"):
            source = ROOT / "src/boards" / board
            result, output = self.inventory(board, (source / "board.cmake").read_text(),
                                             (source / "board.mk").read_text())
            self.assertEqual(0, result)
            self.assertIn("1 profiles, 1 unique targets", output)

    def test_real_inventory_still_imports_and_validates(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, checker.main())


if __name__ == "__main__":
    unittest.main()
