#!/usr/bin/env python3
"""Host tests for the guarded physical UF2 drive-copy runner."""

from __future__ import annotations

import hashlib
from contextlib import ExitStack
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "uf2_drive_hil.py"
SPEC = importlib.util.spec_from_file_location("uf2_drive_hil", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
hil = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = hil
SPEC.loader.exec_module(hil)


FAMILY = 0xADA52840
APP_BASE = 0x26000
APP_LIMIT = 0xEA000


def uf2_block(
    number: int,
    count: int,
    target: int,
    family: int = FAMILY,
    flags: int = hil.UF2_FLAG_FAMILY_ID_PRESENT,
) -> bytes:
    block = bytearray(hil.UF2_BLOCK_SIZE)
    struct.pack_into(
        "<IIIIIIII",
        block,
        0,
        hil.UF2_MAGIC_START0,
        hil.UF2_MAGIC_START1,
        flags,
        target,
        16,
        number,
        count,
        family,
    )
    block[32:48] = bytes((number + index) & 0xFF for index in range(16))
    struct.pack_into("<I", block, 508, hil.UF2_MAGIC_END)
    return bytes(block)


def write_uf2(directory: str, blocks: list[bytes]) -> tuple[Path, str]:
    path = Path(directory) / "application.uf2"
    data = b"".join(blocks)
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


class Uf2InspectionTests(unittest.TestCase):
    def inspect(self, path: Path, digest: str) -> hil.Uf2Image:
        return hil.inspect_application_uf2(
            path, digest, FAMILY, APP_BASE, APP_LIMIT
        )

    def test_complete_hash_pinned_application_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path, digest = write_uf2(
                directory,
                [
                    uf2_block(0, 2, APP_BASE),
                    uf2_block(1, 2, APP_BASE + 16),
                ],
            )
            image = self.inspect(path, digest)
        self.assertEqual(image.blocks, 2)
        self.assertEqual(image.first_address, "0x26000")
        self.assertEqual(image.final_address, "0x26020")

    def test_digest_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path, _ = write_uf2(directory, [uf2_block(0, 1, APP_BASE)])
            with self.assertRaisesRegex(hil.HilError, "SHA-256 mismatch"):
                self.inspect(path, "0" * 64)

    def test_bootloader_family_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path, digest = write_uf2(
                directory,
                [uf2_block(0, 1, APP_BASE, hil.BOOTLOADER_UF2_FAMILY)],
            )
            with self.assertRaisesRegex(hil.HilError, "bootloader-update UF2"):
                hil.inspect_application_uf2(
                    path,
                    digest,
                    hil.BOOTLOADER_UF2_FAMILY,
                    APP_BASE,
                    APP_LIMIT,
                )

    def test_wrong_application_base_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path, digest = write_uf2(
                directory, [uf2_block(0, 1, APP_BASE + 0x1000)]
            )
            with self.assertRaisesRegex(hil.HilError, "starts at"):
                self.inspect(path, digest)

    def test_duplicate_block_number_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path, digest = write_uf2(
                directory,
                [
                    uf2_block(0, 2, APP_BASE),
                    uf2_block(0, 2, APP_BASE + 16),
                ],
            )
            with self.assertRaisesRegex(hil.HilError, "duplicated"):
                self.inspect(path, digest)

    def test_write_at_bootloader_boundary_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path, digest = write_uf2(
                directory,
                [
                    uf2_block(0, 2, APP_BASE),
                    uf2_block(1, 2, APP_LIMIT),
                ],
            )
            with self.assertRaisesRegex(hil.HilError, "allowed range"):
                self.inspect(path, digest)


class IdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.selected = hil.UsbIdentity(
            "/dev/ttyACM0",
            "0b81c9c68d8d01b4",
            "pci-0000:00:14.0-usb-0:3",
            "239a",
            "8029",
            "MeshCore",
            "00",
        )
        self.profile = hil.BoardProfile(
            "wiscore_rak3401",
            "239a",
            "0029",
            "RAK3401",
            "WisBlock RAK3401",
            "WisBlock-RAK3401",
            "nrf52840",
            APP_LIMIT,
        )

    def test_usb_path_discards_only_interface_component(self) -> None:
        self.assertEqual(
            hil.usb_path_stem("pci-0000:00:14.0-usb-0:3:1.1"),
            "pci-0000:00:14.0-usb-0:3",
        )
        self.assertEqual(
            hil.usb_path_stem("pci-0000:00:14.0-usb-0:3:1.0-scsi-0:0:0:0"),
            "pci-0000:00:14.0-usb-0:3",
        )

    def test_conflicting_serial_rejects_same_path(self) -> None:
        candidate = hil.UsbIdentity(
            "/dev/sda",
            "different",
            self.selected.path_stem,
            "239a",
            "0029",
            "RAK3401",
            "00",
        )
        self.assertFalse(hil.same_physical_device(candidate, self.selected))

    def test_matching_serial_does_not_override_changed_usb_path(self) -> None:
        candidate = hil.UsbIdentity(
            "/dev/sda",
            self.selected.serial,
            "pci-0000:00:14.0-usb-0:9",
            "239a",
            "0029",
            "RAK3401",
            "00",
        )
        self.assertFalse(hil.same_physical_device(candidate, self.selected))

    def test_exact_boot_drive_is_selected(self) -> None:
        records = [
            {
                "name": "/dev/sda",
                "type": "disk",
                "fstype": "vfat",
                "label": "RAK3401",
                "mountpoints": ["/media/RAK3401"],
            },
            {
                "name": "/dev/sdb",
                "type": "disk",
                "fstype": "vfat",
                "label": "RAK3401",
                "mountpoints": ["/media/other"],
            },
        ]
        identities = {
            "/dev/sda": hil.UsbIdentity(
                "/dev/sda",
                self.selected.serial,
                self.selected.path_stem,
                "239a",
                "0029",
                "RAK3401",
                "00",
            ),
            "/dev/sdb": hil.UsbIdentity(
                "/dev/sdb",
                "another",
                "pci-0000:00:14.0-usb-0:4",
                "239a",
                "0029",
                "RAK3401",
                "00",
            ),
        }
        matches = hil.matching_block_devices(
            records, self.selected, self.profile, identities.__getitem__
        )
        self.assertEqual([match.node for match in matches], ["/dev/sda"])

    def test_return_selects_original_cdc_interface(self) -> None:
        other_interface = hil.UsbIdentity(
            "/dev/ttyACM1",
            self.selected.serial,
            self.selected.path_stem,
            self.selected.vid,
            self.selected.pid,
            self.selected.product,
            "02",
        )
        identities = {
            "/dev/ttyACM0": self.selected,
            "/dev/ttyACM1": other_interface,
        }
        with (
            mock.patch.object(
                hil, "list_tty_nodes", return_value=list(identities)
            ),
            mock.patch.object(hil, "usb_identity", side_effect=identities.__getitem__),
        ):
            matches = hil.matching_application_ports(self.selected)
        self.assertEqual(matches, [self.selected])

    def test_board_profile_comes_from_board_header(self) -> None:
        profile = hil.load_board_profile("wiscore_rak3401")
        self.assertEqual(profile.boot_vid, "239a")
        self.assertEqual(profile.boot_pid, "0029")
        self.assertEqual(profile.volume_label, "RAK3401")
        self.assertEqual(profile.application_limit, APP_LIMIT)


class CopyAndKernelTests(unittest.TestCase):
    def test_owned_mount_is_unmounted_before_waiting_for_application(self) -> None:
        selected = hil.UsbIdentity("/dev/ttyACM0", "1234", "usb-1.1", "239a", "8029", "RAK3401", "00")
        block = hil.BlockDevice("/dev/sda", "vfat", "RAK3401", (), selected)
        image = hil.Uf2Image("app.uf2", "0" * 64, 512, 1, "0xADA52840", "0x26000", "0x26100")
        result = hil.CommandResult(0, "expected", 0.1)
        args = SimpleNamespace(board="wiscore_rak3401", application=Path("app.uf2"),
                               sha256="0" * 64, family=FAMILY, app_base=APP_BASE,
                               meshcli="meshcli", companion_terminal=True, port=Path(selected.node),
                               serial=selected.serial, verify_command="ver", expect_before_reply="expected",
                               expect_reply="expected", execute=True, skip_kernel_log=False,
                               enumeration_timeout=30, copy_timeout=30, return_timeout=30)
        calls = []
        stubs = {
            "inspect_application_uf2": image, "check_dependencies": "meshcli",
            "check_noninteractive_privilege": None, "usb_identity": selected,
            "modem_manager_is_active": False, "verify_application_reply": result,
            "read_kernel_log": ["unchanged kernel log"], "serial_text_command": result,
            "wait_for_block_device": block, "mount_block_device": ("/tmp/uf2", True),
            "revalidate_block_and_mount": block,
        }
        with ExitStack() as stack:
            for name, value in stubs.items():
                stack.enter_context(mock.patch.object(hil, name, return_value=value))
            stack.enter_context(mock.patch.object(hil, "copy_and_sync", side_effect=lambda *a:
                                                  (calls.append("copy/sync") or (result, result))))
            unmount = stack.enter_context(mock.patch.object(hil, "unmount_owned", side_effect=lambda *a:
                                                            calls.append("unmount")))
            stack.enter_context(mock.patch.object(hil, "wait_for_application", side_effect=lambda *a:
                                                  (calls.append("wait for app") or selected)))
            report = hil.run_hil(args)
        self.assertEqual(calls, ["copy/sync", "unmount", "wait for app"])
        unmount.assert_called_once_with("/tmp/uf2", "/dev/sda")
        self.assertTrue(report["unmounted_before_application_return"])
        self.assertEqual(report["status"], "PASS")

    def test_kernel_capture_uses_pi_compatible_raw_option(self) -> None:
        with (
            mock.patch.object(hil.os, "geteuid", return_value=0),
            mock.patch.object(hil, "run_command", return_value=hil.CommandResult(
                0, "<6>[ 1.000000] boot\n", 0.1
            )) as run,
        ):
            self.assertEqual(hil.read_kernel_log(), ["<6>[ 1.000000] boot"])
        run.assert_called_once_with(["dmesg", "--raw"], timeout=15)

    def test_companion_terminal_entry_is_state_independent(self) -> None:
        self.assertEqual(
            hil.COMPANION_TERMINAL_RESET,
            b"+++MESHCORE-TERM-STOP\r\n+++MESHCORE-TERM-START\r\n",
        )

    def test_copy_is_followed_by_mount_scoped_sync(self) -> None:
        commands: list[list[str]] = []

        def execute(command: list[str], **_: object) -> hil.CommandResult:
            commands.append(command)
            return hil.CommandResult(0, "", 0.1)

        with mock.patch.object(hil.os, "geteuid", return_value=0):
            hil.copy_and_sync(Path("/tmp/application.uf2"), "/mnt/uf2", 30, execute)
        self.assertEqual(
            commands,
            [
                ["cp", "--", "/tmp/application.uf2", "/mnt/uf2/application.uf2"],
                ["sync", "-f", "--", "/mnt/uf2"],
            ],
        )

    def test_kernel_delta_and_known_storage_error(self) -> None:
        delta = hil.kernel_log_delta(
            ["old one", "old two"],
            ["old one", "old two", "FAT-fs (sda): error, fat_get_cluster"],
        )
        with self.assertRaisesRegex(hil.HilError, "storage I/O errors"):
            hil.verify_no_kernel_io_errors(delta)


if __name__ == "__main__":
    unittest.main()
