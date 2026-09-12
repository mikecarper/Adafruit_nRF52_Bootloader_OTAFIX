"""Every curated board's Secure package identity and SoftDevice layout agree."""
import ctypes
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import unittest
import os
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from secure_dfu_target import hardware_version, target
from generate_secure_dfu_test import init_packet
from otafix_secure_ble_dfu_test import package


class Targets(unittest.TestCase):
    def test_all_boards_unique_and_softdevice_builds_agree(self):
        ids = set()
        for folder in sorted((ROOT/'src/boards').iterdir()):
            if not (folder/'board.cmake').exists():
                continue
            with self.subTest(board=folder.name):
                profile = target(folder.name)
                self.assertNotIn(profile['hw_version'], ids)
                ids.add(profile['hw_version'])
                self.assertNotIn(profile['hw_version'], (0, 0xFFFFFFFF))
                mk = (folder/'board.mk').read_text()
                make_sd = re.search(r'SD_VERSION\s*=\s*([\d.]+)', mk)
                expected = (0x27000, 0x0123) if make_sd and make_sd[1] == '7.3.0' else (0x26000, 0xB6)
                self.assertEqual((profile['app_base'], profile['fwid']), expected)
                image = struct.pack('<II', 0x20030000, profile['app_base']+9)+bytes(248)
                self.assertTrue(init_packet(image, **profile))
                wrong = struct.pack('<II', 0x20030000, 0x1001)+bytes(248)
                with self.assertRaises(ValueError):
                    init_packet(wrong, **profile)
        self.assertEqual(len(ids), 27)
        self.assertEqual(hardware_version('wiscore_rak3401'), 0x3401)

    def test_invalid_board_refused(self):
        for board in ('../wiscore_rak3401', '', 'unknown', '/tmp'):
            with self.assertRaises(ValueError):
                hardware_version(board)

    def test_package_cli_roundtrip_store_and_wrong_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            for board in ('wiscore_rak3401', 'heltec_t096', 'xiao_nrf52840_ble'):
                profile = target(board)
                image = struct.pack('<II', 0x20030000, profile['app_base']+9)+bytes(248)
                binary, archive = Path(tmp)/(board+'.bin'), Path(tmp)/(board+'.zip')
                binary.write_bytes(image)
                result = subprocess.run([sys.executable, str(ROOT/'tools/generate_secure_dfu_test.py'),
                                         '--board', board, '--application', str(binary), '--output', str(archive)],
                                        text=True, capture_output=True, check=True)
                import json
                metadata = json.loads(result.stdout)
                self.assertEqual(metadata['board'], board)
                self.assertEqual(package(archive, metadata['zip_sha256'], board),
                                 (image, init_packet(image, **profile)))
                with zipfile.ZipFile(archive) as z:
                    self.assertTrue(all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist()))
                with self.assertRaises(ValueError):
                    package(archive, metadata['zip_sha256'], 'heltec_t114')

    def test_build_rejects_non_test_or_unsupported_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            for label, flags in (
                ('no-version', []),
                ('signed', ['-DSIGNED_FW=ON']),
                ('dualbank', ['-DDUALBANK_FW=ON']),
                ('recovery', ['-DRECOVERY_ALLOW_ALL_BOARDS=ON']),
            ):
                options = [] if label == 'no-version' else [
                    '-DMOTA_BOOTLOADER_TEST_BUILD=ON', '-DMOTA_BOOTLOADER_VERSION_TEST_OVERRIDE=0x02040709']
                result = subprocess.run(['cmake', '-S', str(ROOT), '-B', str(Path(tmp)/label),
                                         '-DBOARD=heltec_t096', '-DSECURE_DFU_TEST=ON', *options, *flags],
                                        text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('SECURE_DFU_TEST requires unsigned single-bank', result.stdout+result.stderr)

    def test_real_parser_accepts_own_board_and_rejects_other_board(self):
        # High-bit 32-bit hardware IDs and both SoftDevice generations run through
        # the actual C parser, not a second Python implementation.
        with tempfile.TemporaryDirectory() as tmp:
            for board in ('heltec_t096', 'heltec_t114', 'xiao_nrf52840_ble'):
                profile = target(board)
                libpath = Path(tmp)/(board+('.dll' if os.name == 'nt' else '.so'))
                subprocess.run([os.environ.get('CC','gcc'), '-std=c11', '-shared', '-fPIC', '-O2',
                                '-DSECURE_DFU_HW_VERSION='+str(profile['hw_version']), '-I'+str(ROOT/'src'),
                                str(ROOT/'src/secure_dfu.c'), str(ROOT/'src/sha256.c'),
                                str(ROOT/'test/secure_dfu_host.c'), '-o', str(libpath)], check=True)
                lib = ctypes.CDLL(str(libpath))
                parse = lib.secure_dfu_parse_command
                parse.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint16, ctypes.c_void_p]
                parse.restype = ctypes.c_bool
                image = struct.pack('<II', 0x20030000, profile['app_base']+9)+bytes(248)
                dat = init_packet(image, **profile)
                output = ctypes.create_string_buffer(36)
                self.assertTrue(parse(dat,len(dat),0xEA000-profile['app_base'],profile['fwid'],output))
                other = init_packet(image, **{**profile,'hw_version':0x3401})
                self.assertFalse(parse(other,len(other),0xEA000-profile['app_base'],profile['fwid'],output))
                self.assertFalse(parse(dat,len(dat),0xEA000-profile['app_base'],profile['fwid']^1,output))
                # Overlong fixed envelope tag is noncanonical and must not pass.
                bad = b'\x8a\x00'+dat[1:]
                self.assertFalse(parse(bad,len(bad),0xEA000-profile['app_base'],profile['fwid'],output))
                if os.name == 'nt':
                    import _ctypes
                    _ctypes.FreeLibrary(lib._handle)


if __name__ == '__main__':
    unittest.main(verbosity=2)
