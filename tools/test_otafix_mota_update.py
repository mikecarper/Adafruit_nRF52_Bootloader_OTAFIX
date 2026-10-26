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


class DownloadProgressTests(unittest.TestCase):
    MID = "57CBECA2"
    HASH = "C9479891C5D0446D"
    TRUNCATED_READY = (
        "OTA | this fw 75134BA6 (609K) hw=Heltec_tower_v2 | target:0A9DBBF0 | "
        "maxblk:2048 | bl:SD blrc:B8 | bootloader download: ready to install "
        "40/40 (100%) id=57CBEC"
    )
    STAGED_NONE = (
        "BL board=239A0071 target=1150F50E name=TOWER_V2_OTA "
        "crc=D48D45A9 abi=3 caps=09 | staged:none mid=- hash=-"
    )

    def staged(self, mid: str = MID, image_hash: str = HASH) -> str:
        return self.STAGED_NONE.split(" | ")[0] + f" | staged:ready mid={mid} hash={image_hash}"

    def check(self, status: str) -> bool | None:
        return updater.check_download_progress(None, "tty-target", status, self.MID, self.HASH)

    def test_real_159_byte_completion_uses_exact_staged_pair(self) -> None:
        self.assertEqual(len(self.TRUNCATED_READY), 159)
        with mock.patch.object(updater, "mesh_command", return_value=self.staged()) as command:
            self.assertIs(self.check(self.TRUNCATED_READY), True)
        command.assert_called_once_with(None, "tty-target", "ota bootloader")

    def test_completion_with_omitted_progress_id_uses_staged_pair(self) -> None:
        with mock.patch.object(updater, "mesh_command", return_value=self.staged()):
            self.assertIs(self.check("bootloader download: ready to install 40/40 (100%)"), True)

    def test_truncated_progress_is_confirmed_by_compact_fetch_id(self) -> None:
        stats = "OTA | fw v1.18.0.1 id=A99EF3E6 | serv 1 | fetch dl 12/40 30% id=57CBECA2 42s | af=off"
        with mock.patch.object(updater, "mesh_command", side_effect=[self.STAGED_NONE, stats]) as command:
            self.assertIs(self.check("bootloader download: downloading 12/40 (30%) id=57"), False)
        self.assertEqual(command.call_args_list, [
            mock.call(None, "tty-target", "ota bootloader"),
            mock.call(None, "tty-target", "ota stats"),
        ])

    def test_full_progress_mid_keeps_existing_polling_path(self) -> None:
        for state, ready in (("downloading", False), ("ready to install", True)):
            with self.subTest(state=state), mock.patch.object(updater, "mesh_command") as command:
                self.assertIs(self.check(f"bootloader download: {state} 40/40 (100%) id={self.MID} 159s"), ready)
                command.assert_not_called()

    def test_other_matching_id_cannot_mask_wrong_download_id(self) -> None:
        with mock.patch.object(updater, "mesh_command") as command:
            with self.assertRaisesRegex(updater.UpdateError, "MID DEADBEEF"):
                self.check(f"OTA fw id={self.MID} | bootloader download: downloading 1/40 (2%) id=DEADBEEF")
            command.assert_not_called()

    def test_readiness_is_scoped_to_download_state(self) -> None:
        with mock.patch.object(updater, "mesh_command") as command:
            self.assertIs(self.check(
                f"bootloader download: downloading 12/40 (30%) id={self.MID} | another image ready to install"
            ), False)
            command.assert_not_called()

    def test_wrong_truncated_prefix_is_not_accepted(self) -> None:
        with self.assertRaisesRegex(updater.UpdateError, "MID 57AB"):
            self.check("bootloader download: downloading 1/40 (2%) id=57AB")

    def test_staged_mismatched_mid_or_hash_refuses_completion(self) -> None:
        for mid, image_hash in (("DEADBEEF", self.HASH), (self.MID, "C9479891C5D0446E")):
            with self.subTest(mid=mid, image_hash=image_hash):
                with mock.patch.object(updater, "mesh_command", return_value=self.staged(mid, image_hash)):
                    with self.assertRaisesRegex(updater.UpdateError, "does not match"):
                        self.check(self.TRUNCATED_READY)

    def test_overlong_or_truncated_staged_hash_is_not_exact_confirmation(self) -> None:
        for image_hash in (self.HASH + "F", self.HASH[:-1]):
            with self.subTest(image_hash=image_hash):
                with mock.patch.object(updater, "mesh_command", return_value=self.staged(image_hash=image_hash)):
                    with self.assertRaisesRegex(updater.UpdateError, "complete staged"):
                        self.check(self.TRUNCATED_READY)

    def test_stats_running_firmware_id_does_not_confirm_wrong_fetch(self) -> None:
        stats = f"OTA | fw v1.18.0.1 id={self.MID} | serv 1 | fetch dl 12/40 30% id=DEADBEEF 42s"
        with mock.patch.object(updater, "mesh_command", side_effect=[self.STAGED_NONE, stats]):
            with self.assertRaisesRegex(updater.UpdateError, "MID DEADBEEF"):
                self.check("bootloader download: downloading 12/40 (30%)")

    def test_stats_done_does_not_replace_staged_hash_confirmation(self) -> None:
        stats = f"OTA | fw v? id=? | serv 1 | fetch done 40/40 100% id={self.MID} 159s"
        with mock.patch.object(updater, "mesh_command", side_effect=[self.STAGED_NONE, stats]):
            self.assertIs(self.check(self.TRUNCATED_READY), False)

    def test_missing_or_unsupported_fallback_is_unconfirmed(self) -> None:
        for stats in (f"OTA | fw v1.18.0.1 id={self.MID} | fetch idle", "Unknown OTA command"):
            with self.subTest(stats=stats):
                with mock.patch.object(updater, "mesh_command", side_effect=[self.STAGED_NONE, stats]):
                    self.assertIsNone(self.check("bootloader download: downloading 1/40 (2%) id="))

    def test_unconfirmed_progress_has_finite_poll_budget(self) -> None:
        replies = ["bootloader download: downloading 1/40 (2%)", self.STAGED_NONE, "Unknown OTA command"]
        with mock.patch.object(updater, "mesh_command", side_effect=replies * 3) as command, \
                mock.patch.object(updater.time, "monotonic", return_value=0), \
                mock.patch.object(updater.time, "sleep") as sleep, \
                mock.patch("builtins.print"):
            with self.assertRaisesRegex(updater.UpdateError, "cannot confirm requested MID"):
                updater.wait_for_bootloader_download(None, "tty-target", self.MID, self.HASH,
                                                      FakeProcess(), Path("seeder.log"), 60)
        self.assertEqual(command.call_count, 9)
        self.assertEqual(sleep.call_count, 2)
        self.assertFalse(any("install" in call.args[2] for call in command.call_args_list))

    def test_confirmed_progress_resets_unconfirmed_poll_budget(self) -> None:
        states = [None, None, False, None, None, True]
        with mock.patch.object(updater, "mesh_command", return_value="status") as command, \
                mock.patch.object(updater, "check_download_progress", side_effect=states), \
                mock.patch.object(updater.time, "monotonic", return_value=0), \
                mock.patch.object(updater.time, "sleep"), mock.patch("builtins.print"):
            updater.wait_for_bootloader_download(None, "tty-target", self.MID, self.HASH,
                                                  FakeProcess(), Path("seeder.log"), 60)
        self.assertEqual(command.call_count, len(states))


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


class TowerPackageSelectionTests(unittest.TestCase):
    def test_storage_match_is_required_even_with_only_one_tower_package(self) -> None:
        sd = {"target_id": "0x1150F50E", "board": "heltec_mesh_tower_v2_sdcard"}
        internal = {"target_id": "0x1150F50E", "board": "heltec_mesh_tower_v2"}
        for packages in ([sd], [internal], [sd, internal]):
            for caps, expected in ((9, sd), (10, internal)):
                identity = updater.NodeIdentity("239A0071", "1150F50E", "TOWER_V2_OTA", "00000000", 3, caps)
                with self.subTest(packages=packages, caps=caps), mock.patch.object(updater, "choose") as choose:
                    if expected in packages:
                        self.assertEqual(updater.select_package({"packages": packages}, identity), expected)
                    else:
                        with self.assertRaisesRegex(updater.UpdateError, "local normal bootloader"):
                            updater.select_package({"packages": packages}, identity)
                    choose.assert_not_called()

    def test_unknown_tower_storage_does_not_guess(self) -> None:
        identity = updater.NodeIdentity("239A0071", "1150F50E", "TOWER_V2_OTA", "00000000", 3, 0x0B)
        with self.assertRaisesRegex(updater.UpdateError, "unsupported MeshTower"):
            updater.select_package({"packages": [{"target_id": "0x1150F50E", "board": "heltec_mesh_tower_v2_sdcard"}]}, identity)


class CompanionTerminalTests(unittest.TestCase):
    def test_reset_sequence_is_state_independent(self) -> None:
        self.assertEqual(
            updater.COMPANION_TERMINAL_RESET,
            b"+++MESHCORE-TERM-STOP\r\n+++MESHCORE-TERM-START\r\n",
        )


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
