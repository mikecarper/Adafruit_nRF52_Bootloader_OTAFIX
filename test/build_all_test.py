#!/usr/bin/env python3
"""Regression tests for the isolated all-board qualification helper."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "otafix_build_all", ROOT / "tools" / "build_all.py"
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load tools/build_all.py")
BUILD_ALL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD_ALL)


class BuildAllTest(unittest.TestCase):
    def test_selects_current_named_output_with_stale_artifacts_present(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otafix-build-all-") as temporary:
            build_root = Path(temporary)
            board_build = build_root / "build-heltec_t096"
            board_build.mkdir()
            current = board_build / "current-qualified.out"
            stale = board_build / "stale-old-version.out"
            current.write_bytes(b"current")
            stale.write_bytes(b"stale")

            calls: list[list[object]] = []

            def fake_run(command, **kwargs):
                calls.append(command)
                if command[-1] == "all":
                    return subprocess.CompletedProcess(command, 0, stdout="build ok\n")
                if command[-1] == "print-OUT_NAME":
                    return subprocess.CompletedProcess(
                        command, 0, stdout="OUT_NAME = current-qualified\n"
                    )
                raise AssertionError(f"unexpected command: {command}")

            with mock.patch.object(BUILD_ALL.subprocess, "run", side_effect=fake_run), \
                 mock.patch.object(BUILD_ALL, "image_sizes", return_value=(123, 45)) as sizes:
                result = BUILD_ALL.build_board(
                    "heltec_t096", 1, "0x02040403", "arm-none-eabi-size", build_root
                )

            self.assertTrue(result[1], result[-1])
            self.assertEqual((123, 45), result[3:5])
            sizes.assert_called_once_with("arm-none-eabi-size", current)
            self.assertEqual(2, len(calls))
            self.assertIn(f"BUILD={board_build}", calls[0])
            self.assertIn("MOTA_BOOTLOADER_TEST_BUILD=1", calls[0])
            self.assertIn(
                "MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=0x02040403", calls[0]
            )

    def test_never_substitutes_a_stale_output_for_a_missing_current_one(self) -> None:
        with tempfile.TemporaryDirectory(prefix="otafix-build-all-") as temporary:
            build_root = Path(temporary)
            board_build = build_root / "build-heltec_t114"
            board_build.mkdir()
            (board_build / "stale-old-version.out").write_bytes(b"stale")

            def fake_run(command, **kwargs):
                output = (
                    "OUT_NAME = missing-current\n"
                    if command[-1] == "print-OUT_NAME"
                    else "build ok\n"
                )
                return subprocess.CompletedProcess(command, 0, stdout=output)

            with mock.patch.object(BUILD_ALL.subprocess, "run", side_effect=fake_run), \
                 mock.patch.object(BUILD_ALL, "image_sizes") as sizes:
                result = BUILD_ALL.build_board(
                    "heltec_t114", 1, None, "arm-none-eabi-size", build_root
                )

            self.assertFalse(result[1])
            self.assertIn("expected current output", result[-1])
            sizes.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
