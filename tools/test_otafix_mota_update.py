#!/usr/bin/env python3
"""Focused tests for the OTAFIX MeshCore updater helpers."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

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

    def test_empty_catalog_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_log(directory, "  [dev] COUNT -> 0\n")
            with self.assertRaisesRegex(updater.UpdateError, "empty catalog"):
                updater.wait_for_seeder_attachment(FakeProcess(), path, timeout=0)

    def test_latest_count_overrides_stale_nonempty_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_log(directory, "[dev] COUNT -> 1\n[dev] COUNT -> 0\n")
            with self.assertRaisesRegex(updater.UpdateError, "empty catalog"):
                updater.wait_for_seeder_attachment(FakeProcess(), path, timeout=0)

    def test_count_does_not_mask_device_error_or_process_exit(self) -> None:
        for code, suffix, error in (
            (None, "[dev] ERR folder already owned\n", "could not attach"),
            (7, "", "status 7"),
        ):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                path = self.write_log(directory, "[dev] COUNT -> 1\n" + suffix)
                with self.assertRaisesRegex(updater.UpdateError, error):
                    updater.wait_for_seeder_attachment(FakeProcess(code), path, timeout=0)

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


class AdaptiveRecoveryTests(unittest.TestCase):
    def test_only_exact_adaptive_identities_can_use_abi_two(self) -> None:
        version = "OTAFIX2.4.8"
        for target, name in (("D04AB3AB", "3401_AUTO_DFU"),
                             ("FEEAFD1B", "4631_AUTO_DFU")):
            identity = (f"BL board=239A0029 target={target} name={name} "
                        "crc=12345678 abi=2 caps=16")
            with self.subTest(name=name), mock.patch.object(
                updater, "mesh_command", side_effect=[version, identity]
            ):
                _, _, parsed = updater.query_node(None, "/dev/test")
                self.assertTrue(updater.is_adaptive_recovery(parsed))
        for target, name, caps in (("D04AB3AC", "3401_AUTO_DFU", "16"),
                                   ("D04AB3AB", "4631_AUTO_DFU", "16"),
                                   ("D04AB3AB", "3401_AUTO_DFU", "0A")):
            identity = (f"BL board=239A0029 target={target} name={name} "
                        f"crc=12345678 abi=2 caps={caps}")
            with self.subTest(identity=identity), mock.patch.object(
                updater, "mesh_command", side_effect=[version, identity]
            ), self.assertRaisesRegex(updater.UpdateError, "unsupported bootloader capability"):
                updater.query_node(None, "/dev/test")

    def test_recovery_refuses_equal_version_before_fetch(self) -> None:
        identity = updater.NodeIdentity(
            "239A0029", "D04AB3AB", "3401_AUTO_DFU", "12345678", 2, 0x16
        )
        current = updater.Version(2, 4, 8, 255, "2.4.8")
        release = mock.Mock(version=updater.Version(2, 4, 8, 255, "2.4.8"))
        with mock.patch.object(updater, "prepare_package") as prepare:
            with self.assertRaisesRegex(updater.UpdateError, "requires a newer"):
                updater.install_update(mock.Mock(), None, "motatool", "/dev/test",
                                       current, identity, release)
            prepare.assert_not_called()


class OfflineFieldBundleTests(unittest.TestCase):
    def write_bundle(self, directory: str, key: str | None = None) -> Path:
        path = Path(directory) / "GAT562-OTAFIX-2.4.5-LoRa-bundle.zip"
        signer = key or updater.OFFICIAL_PUBLIC_KEY
        manifest = {
            "tag": "0.11.0-OTAFIX2.4.5",
            "signing_public_key": signer,
            "packages": [],
        }
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("OTAFIX_MOTA_SIGNING_PUBLIC_KEY.txt", signer + "\n")
        return path

    def test_local_bundle_selects_release_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release = updater.load_local_release(self.write_bundle(directory))
        self.assertEqual(release.tag, "0.11.0-OTAFIX2.4.5")
        self.assertEqual(release.version.label, "2.4.5")
        self.assertIsNotNone(release.local_bundle)
        self.assertEqual(len(release.bundle_digest), 64)

    def test_local_bundle_rejects_any_other_signer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_bundle(directory, key="00" * 32)
            with self.assertRaisesRegex(updater.UpdateError, "pinned official key"):
                updater.load_local_release(path)

    def test_local_bundle_rejects_unsafe_noncanonical_tag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_bundle(directory)
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "manifest.json",
                    json.dumps(
                        {
                            "tag": "../../OTAFIX2.4.5",
                            "signing_public_key": updater.OFFICIAL_PUBLIC_KEY,
                            "packages": [],
                        }
                    ),
                )
                archive.writestr(
                    "OTAFIX_MOTA_SIGNING_PUBLIC_KEY.txt",
                    updater.OFFICIAL_PUBLIC_KEY + "\n",
                )
            with self.assertRaisesRegex(updater.UpdateError, "canonical"):
                updater.load_local_release(path)

    def test_direct_serial_mode_retries_without_meshcli(self) -> None:
        with mock.patch.object(
            updater,
            "serial_text_command",
            side_effect=["", "OTAFIX2.4.5"],
        ) as command:
            reply = updater.mesh_command(None, "/dev/ttyACM0", "get bootloader.ver")
        self.assertEqual(reply, "OTAFIX2.4.5")
        self.assertEqual(command.call_count, 2)
        command.assert_called_with(
            "/dev/ttyACM0", "get bootloader.ver", companion=False
        )

    def test_field_identity_gate_compares_every_stable_field(self) -> None:
        identity = updater.NodeIdentity(
            "239A0029", "D50D2D44", "GAT562_DFU", "12345678", 3, 0x0A
        )
        updater.require_identity(
            "239A0029,D50D2D44,GAT562_DFU,3,0A", identity
        )
        for wrong in (
            "239A0028,D50D2D44,GAT562_DFU,3,0A",
            "239A0029,D50D2D45,GAT562_DFU,3,0A",
            "239A0029,D50D2D44,4631_DFU,3,0A",
            "239A0029,D50D2D44,GAT562_DFU,2,0A",
            "239A0029,D50D2D44,GAT562_DFU,3,09",
        ):
            with self.subTest(wrong=wrong), self.assertRaises(updater.UpdateError):
                updater.require_identity(wrong, identity)


if __name__ == "__main__":
    unittest.main()
