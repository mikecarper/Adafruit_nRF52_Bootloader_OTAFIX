#!/usr/bin/env python3
"""Exercise the bundled UF2 converter's platform drive discovery."""

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "lib" / "uf2" / "utils" / "uf2conv.py"
SPEC = importlib.util.spec_from_file_location("uf2conv_discovery", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
uf2conv = importlib.util.module_from_spec(SPEC)
with mock.patch.object(sys, "dont_write_bytecode", True):
    SPEC.loader.exec_module(uf2conv)


class Uf2ConverterDiscoveryTest(unittest.TestCase):
    def test_windows_queries_fat_volumes_and_requires_uf2_marker(self):
        # PowerShell emits drive letters without the old WMIC column table.
        # Plain FAT volumes, inaccessible markers and empty lines cannot become
        # firmware destinations; whitespace and CRLF must not hide UF2 drives.
        def has_marker(path):
            if path == "F:/INFO_UF2.TXT":
                raise OSError("drive disappeared")
            return path in {"D:/INFO_UF2.TXT", "G:/INFO_UF2.TXT"}

        with mock.patch.object(uf2conv.sys, "platform", "win32"), \
                mock.patch.object(uf2conv.subprocess, "check_output",
                                  return_value=b"D:\r\n  E:  \r\nF:\r\nG:  \r\n\r\n") as query, \
                mock.patch.object(uf2conv.os.path, "isfile", side_effect=has_marker):
            drives = uf2conv.get_drives()

        self.assertEqual(drives, ["D:", "G:"])
        query.assert_called_once_with([
            "powershell", "-Command",
            '(Get-WmiObject Win32_LogicalDisk -Filter "FileSystem=\'FAT\'").DeviceID',
        ])

    def test_windows_with_no_fat_volumes_returns_no_drives(self):
        with mock.patch.object(uf2conv.sys, "platform", "win32"), \
                mock.patch.object(uf2conv.subprocess, "check_output", return_value=b""), \
                mock.patch.object(uf2conv.os.path, "isfile") as marker:
            self.assertEqual(uf2conv.get_drives(), [])
        marker.assert_not_called()

    def test_linux_keeps_user_and_sudo_mount_discovery(self):
        mounts = {
            "/mnt": ["UF2", "plain", "file"],
            "/media": [],
            "/media/alice": ["UF2"],
            "/run/media/alice": ["plain"],
            "/media/bob": ["UF2"],
            "/run/media/bob": [],
        }
        directories = set(mounts) | {
            "/mnt/UF2", "/mnt/plain", "/media/alice/UF2",
            "/run/media/alice/plain", "/media/bob/UF2",
        }
        markers = {
            "/mnt/UF2/INFO_UF2.TXT", "/media/alice/UF2/INFO_UF2.TXT",
            "/media/bob/UF2/INFO_UF2.TXT",
        }
        with mock.patch.object(uf2conv.sys, "platform", "linux"), \
                mock.patch.dict(uf2conv.os.environ, {"USER": "alice", "SUDO_USER": "bob"}, clear=True), \
                mock.patch.object(uf2conv.os, "listdir", side_effect=mounts.__getitem__), \
                mock.patch.object(uf2conv.os.path, "isdir", side_effect=directories.__contains__), \
                mock.patch.object(uf2conv.os.path, "isfile", side_effect=markers.__contains__), \
                mock.patch.object(uf2conv.subprocess, "check_output") as query:
            drives = uf2conv.get_drives()

        self.assertEqual(drives, ["/mnt/UF2", "/media/alice/UF2", "/media/bob/UF2"])
        query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
