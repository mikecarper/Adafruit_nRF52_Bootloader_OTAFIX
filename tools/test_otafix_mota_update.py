#!/usr/bin/env python3
"""Focused tests for the OTAFIX MeshCore updater helpers."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import otafix_mota_update as updater


class FakeProcess:
    def __init__(self, return_code: int | None = None):
        self.return_code = return_code

    def poll(self) -> int | None:
        return self.return_code


class SeederAttachmentTests(unittest.TestCase):
    def write_log(self, directory: str, text: str) -> Path:
        path = Path(directory) / "motatool.log"
        path.write_text(text, encoding="ascii")
        return path

    def test_count_response_confirms_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_log(directory, "  [dev] COUNT -> 3\n")
            updater.wait_for_seeder_attachment(FakeProcess(), path, timeout=0)

    def test_device_error_rejects_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_log(directory, "  [dev] ERR folder already owned\n")
            with self.assertRaisesRegex(updater.UpdateError, "could not attach"):
                updater.wait_for_seeder_attachment(FakeProcess(), path, timeout=0)

    def test_live_process_without_count_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_log(directory, "serving on tty\n")
            with self.assertRaisesRegex(updater.UpdateError, "COUNT response"):
                updater.wait_for_seeder_attachment(FakeProcess(), path, timeout=0)

    def test_exited_process_reports_status_and_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_log(directory, "serial port closed\n")
            with self.assertRaisesRegex(updater.UpdateError, "status 7"):
                updater.wait_for_seeder_attachment(FakeProcess(7), path, timeout=0)

    def test_log_stream_is_flushed_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "motatool.log"
            with path.open("w", encoding="ascii") as stream:
                stream.write("  [dev] COUNT -> 1\n")
                updater.wait_for_seeder_attachment(
                    FakeProcess(), path, stream, timeout=0
                )


class CompanionTerminalTests(unittest.TestCase):
    def test_reset_sequence_is_state_independent(self) -> None:
        self.assertEqual(
            updater.COMPANION_TERMINAL_RESET,
            b"+++MESHCORE-TERM-STOP\r\n+++MESHCORE-TERM-START\r\n",
        )


if __name__ == "__main__":
    unittest.main()
