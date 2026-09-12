#!/usr/bin/env python3
"""Native tests of the actual resumable protocol, using independent Python CRC/SHA."""
import ctypes
import os
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from generate_secure_dfu_test import init_packet


class Image(ctypes.Structure):
    _fields_ = [('size', ctypes.c_uint32), ('digest', ctypes.c_uint8 * 32)]


class SecureDfuTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='otafix-secure-dfu-test-')
        cls.addClassCleanup(cls.temp.cleanup)
        library = Path(cls.temp.name) / ('protocol.dll' if os.name == 'nt' else 'protocol.so')
        sanitizers = ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-O1', '-g'] \
            if os.environ.get('SECURE_DFU_TEST_SANITIZE') == '1' else []
        subprocess.run([os.environ.get('CC', 'gcc'), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        *sanitizers,
                        '-shared', '-fPIC', '-I' + str(ROOT / 'src'),
                        str(ROOT / 'src/secure_dfu.c'), str(ROOT / 'src/sha256.c'),
                        str(ROOT / 'test/secure_dfu_host.c'), '-o', str(library)], check=True)
        cls.lib = ctypes.CDLL(str(library))
        if os.name == 'nt':
            import _ctypes
            cls.addClassCleanup(lambda: _ctypes.FreeLibrary(cls.lib._handle))
        for name in ('test_control', 'test_packet'):
            f = getattr(cls.lib, name)
            f.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
            f.restype = ctypes.c_size_t
        cls.lib.test_flash.restype = ctypes.c_void_p
        cls.lib.secure_dfu_parse_command.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                                    ctypes.c_uint32, ctypes.c_uint16,
                                                    ctypes.POINTER(Image)]
        cls.lib.secure_dfu_parse_command.restype = ctypes.c_bool
        cls.lib.test_completed.restype = ctypes.c_bool

    def setUp(self):
        self.lib.test_reset()
        self.image = struct.pack('<II', 0x20030000, 0x26009) + bytes((i * 37 + 17) % 256 for i in range(8696))
        self.dat = init_packet(self.image)

    def call(self, name, data):
        out = ctypes.create_string_buffer(15)
        n = getattr(self.lib, name)(data, len(data), out)
        return out.raw[:n]

    def control(self, data, status=1):
        response = self.call('test_control', data)
        self.assertEqual(response[:3], bytes((0x60, data[0], status)))
        return response[3:]

    def select(self, kind):
        return struct.unpack('<III', self.control(bytes((6, kind))))

    def create(self, kind, size, status=1):
        return self.control(bytes((1, kind)) + struct.pack('<I', size), status)

    def packet(self, data):
        response = self.call('test_packet', data)
        if response:
            self.assertEqual(response[:3], b'\x60\x03\x01')
        return response

    def begin(self):
        self.assertEqual(self.select(1), (256, 0, 0))
        self.create(1, len(self.dat))
        self.packet(self.dat)
        self.assertEqual(self.control(b'\x03'), struct.pack('<II', len(self.dat), zlib.crc32(self.dat)))
        self.control(b'\x04')
        self.assertEqual(self.lib.test_begins(), 1)
        self.select(2)

    def write_until(self, start, end, mtu=243):
        at = start
        while at < end:
            take = min(mtu, end - at)
            self.packet(self.image[at:at + take])
            at += take

    def run_transfer(self, drop, after_execute=False):
        self.begin()
        dropped = False
        for start in range(0, len(self.image), 4096):
            end = min(start + 4096, len(self.image))
            self.create(2, end - start)
            if start <= drop <= end and not dropped and not after_execute:
                self.write_until(start, drop)
                # New phone connection: SELECT/CRC command, idempotent EXECUTE,
                # SELECT data and seek its input file to the received byte count.
                self.assertEqual(self.select(1), (256, len(self.dat), zlib.crc32(self.dat)))
                self.control(b'\x04')
                self.assertEqual(self.select(2), (4096, drop, zlib.crc32(self.image[:drop])))
                self.write_until(drop, end, mtu=20)
                dropped = True
            else:
                self.write_until(start, end)
            self.assertEqual(self.control(b'\x03'), struct.pack('<II', end, zlib.crc32(self.image[:end])))
            self.control(b'\x04')
            if after_execute and end == drop:
                self.select(1)
                self.control(b'\x04')
                self.assertEqual(self.select(2), (4096, drop, zlib.crc32(self.image[:drop])))
                self.control(b'\x04')
                dropped = True
        self.assertTrue(dropped)
        self.assertTrue(self.lib.test_completed())
        self.assertEqual(self.lib.test_begins(), 1)
        self.assertEqual(self.lib.test_writes(), 3)
        self.assertEqual(self.lib.test_finishes(), 1)
        self.assertEqual(ctypes.string_at(self.lib.test_flash(), len(self.image)), self.image)
        self.create(1, len(self.dat), 8)

    def test_resume_at_byte_and_object_boundaries(self):
        for drop in (0, 1, 3, 4, 7, 19, 20, 127, 128, 239, 240, 241, 243, 244,
                     4095, 4096, 4097, 8191, 8192, 8193, 8703, 8704):
            with self.subTest(drop=drop):
                self.lib.test_reset()
                self.run_transfer(drop)

    def test_resume_after_execute_receipt_lost(self):
        for drop in (4096, 8192, 8704):
            with self.subTest(drop=drop):
                self.lib.test_reset()
                self.run_transfer(drop, after_execute=True)

    def test_partial_command_resume(self):
        for split in range(1, len(self.dat)):
            self.lib.test_reset()
            self.create(1, len(self.dat))
            self.packet(self.dat[:split])
            self.assertEqual(self.select(1), (256, split, zlib.crc32(self.dat[:split])))
            self.packet(self.dat[split:])
            self.control(b'\x04')
            self.assertEqual(self.lib.test_begins(), 1)

    def test_crc_retry_rolls_back_only_unexecuted_object(self):
        self.begin()
        self.create(2, 4096)
        self.packet(b'wrong content')
        self.create(2, 4096)
        self.assertEqual(self.select(2), (4096, 0, 0))
        self.write_until(0, 4096)
        self.control(b'\x04')
        self.create(2, 4096)
        self.packet(b'another wrong prefix')
        self.create(2, 4096)
        self.assertEqual(self.select(2), (4096, 4096, zlib.crc32(self.image[:4096])))
        self.assertEqual(self.lib.test_writes(), 1)

    def test_prn_crc_and_offset(self):
        self.begin()
        self.create(2, 4096)
        self.control(b'\x02\x08\x00')
        for i in range(8):
            reply = self.packet(self.image[i * 20:(i + 1) * 20])
            self.assertEqual(len(reply), 11 if i == 7 else 0)
        self.assertEqual(reply[3:], struct.pack('<II', 160, zlib.crc32(self.image[:160])))

    def test_bad_final_hash_cannot_activate(self):
        self.begin()
        for start in range(0, len(self.image), 4096):
            end = min(start + 4096, len(self.image))
            self.create(2, end - start)
            self.packet(bytes(end - start))
            self.control(b'\x04', 5 if end == len(self.image) else 1)
        self.assertFalse(self.lib.test_completed())

    def test_write_failure_cannot_activate_or_resume(self):
        self.begin()
        self.create(2, 4096)
        self.packet(self.image[:4096])
        self.lib.test_fail_write()
        self.control(b'\x04', 10)
        self.control(b'\x04', 10)
        self.create(1, len(self.dat), 8)
        self.assertEqual(self.lib.test_begins(), 1)
        self.assertFalse(self.lib.test_completed())

    def test_malformed_metadata_never_begins_flash(self):
        candidates = [self.dat[:n] for n in range(len(self.dat))]
        candidates += [self.dat + b'\x00', b'\x12' + self.dat[1:], self.dat.replace(b'\xB6\x01', b'\xB7\x01'),
                       self.dat.replace(b'\x10\x81\x68', b'\x10\x82\x68'),
                       self.dat.replace(b'\x20\x00', b'\x20\x01')]
        for candidate in candidates:
            if not candidate:
                continue
            with self.subTest(dat=candidate.hex()):
                self.lib.test_reset()
                self.create(1, len(candidate))
                self.packet(candidate)
                self.control(b'\x04', 5)
                self.assertEqual(self.lib.test_begins(), 0)

    def test_invalid_lengths_and_types(self):
        self.control(b'\x06\x00', 7)
        self.control(b'\x7F', 2)
        self.control(b'\x04', 8)
        self.create(1, 257, 3)
        self.create(2, 4096, 8)
        self.begin()
        self.create(2, 4095, 3)
        self.create(2, 4096)
        self.assertEqual(self.call('test_packet', bytes(4097)), b'\x60\x08\x08')
        self.control(b'\x04', 8)
        self.assertEqual(self.lib.test_writes(), 0)

    def test_packet_before_create_does_not_poison_session(self):
        for packet in (b'', b'X'):
            with self.subTest(packet=packet):
                self.lib.test_reset()
                self.assertEqual(self.call('test_packet', packet), b'\x60\x08\x08')
                self.assertEqual(self.lib.test_begins(), 0)
                self.assertEqual(self.lib.test_writes(), 0)
                self.begin()

    def test_rejected_command_packet_preserves_crc_and_allows_retry(self):
        self.create(1, len(self.dat))
        self.packet(self.dat[:20])
        before = self.select(1)
        for packet in (b'', self.dat):
            self.assertEqual(self.call('test_packet', packet), b'\x60\x08\x08')
            self.assertEqual(self.select(1), before)
        self.packet(self.dat[20:])
        self.control(b'\x04')
        # COMMAND is already executed: a stray write must not undo it.
        self.assertEqual(self.call('test_packet', b'X'), b'\x60\x08\x08')
        self.control(b'\x04')
        self.assertEqual(self.lib.test_begins(), 1)

    def test_rejected_data_packet_preserves_object_and_allows_completion(self):
        self.begin()
        # DATA has been selected, but not created yet.
        self.assertEqual(self.call('test_packet', b'X'), b'\x60\x08\x08')
        for start in range(0, len(self.image), 4096):
            end = min(start + 4096, len(self.image))
            self.create(2, end - start)
            self.write_until(start, start + 20)
            before = self.select(2)
            for packet in (b'', bytes(end - start)):
                self.assertEqual(self.call('test_packet', packet), b'\x60\x08\x08')
                self.assertEqual(self.select(2), before)
            self.write_until(start + 20, end)
            self.control(b'\x04')
            self.assertEqual(self.call('test_packet', b'X'), b'\x60\x08\x08')
            self.control(b'\x04')
        self.assertTrue(self.lib.test_completed())
        self.assertEqual(self.lib.test_writes(), 3)
        self.assertEqual(ctypes.string_at(self.lib.test_flash(), len(self.image)), self.image)

    def test_packet_rejection_does_not_clear_flash_failure(self):
        self.begin()
        self.create(2, 4096)
        self.packet(self.image[:4096])
        self.lib.test_fail_write()
        self.control(b'\x04', 10)
        self.assertEqual(self.call('test_packet', b'X'), b'\x60\x08\x08')
        self.create(1, len(self.dat), 8)
        self.create(2, 4096, 8)
        self.control(b'\x04', 10)

    def test_parser_random_inputs(self):
        rng = random.Random(3401)
        parsed = Image()
        for _ in range(10000):
            candidate = rng.randbytes(rng.randrange(1, 280))
            self.assertFalse(self.lib.secure_dfu_parse_command(candidate, len(candidate), 10000, 0xB6,
                                                              ctypes.byref(parsed)))


class SecureDfuBleSourceGuard(unittest.TestCase):
    def test_only_delivered_final_data_execute_can_activate(self):
        # Source guard, not a simulated SoftDevice: the protocol state-machine
        # tests above separately exercise repeated COMMAND/DATA execution.
        source = ' '.join((ROOT / 'src/secure_dfu_ble.c').read_text().split())
        marker = source.split('final_notifications[slot] =', 1)[1].split(';', 1)[0]
        for required in ('control', 'w->len == 1', 'w->data[0] == 4',
                         'session.selected == 2', 'session.completed',
                         'lengths[slot] == 3', 'notifications[slot][2] == 1'):
            self.assertIn(required, marker)
        self.assertIn('if (final_notifications[queue_head])', source)
        self.assertIn('final_response_sent && queue_count == 0 && tx_pending == 0', source)
        self.assertIn('Do not recursively dispatch incoming BLE writes.', source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
