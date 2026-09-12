#!/usr/bin/env python3
"""Check shared production CRC/SHA/watchdog helpers against independent oracles."""
import ctypes
import hashlib
import os
from pathlib import Path
import random
import subprocess
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]


class SharedHelpersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='otafix-shared-helpers-')
        cls.addClassCleanup(cls.temp.cleanup)
        library = Path(cls.temp.name) / ('helpers.dll' if os.name == 'nt' else 'helpers.so')
        sanitizers = ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-O1', '-g'] \
            if os.environ.get('SECURE_DFU_TEST_SANITIZE') == '1' else []
        subprocess.run([os.environ.get('CC', 'gcc'), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        *sanitizers, '-shared', '-fPIC',
                        '-I' + str(ROOT / 'test/shared_helpers_stubs'), '-I' + str(ROOT / 'src'),
                        str(ROOT / 'test/shared_helpers_host.c'), str(ROOT / 'src/sha256.c'),
                        str(ROOT / 'src/usb/uf2/bootloader_image.c'), '-o', str(library)], check=True)
        cls.lib = ctypes.CDLL(str(library))
        if os.name == 'nt':
            import _ctypes
            cls.addClassCleanup(lambda: _ctypes.FreeLibrary(cls.lib._handle))
        cls.lib.test_crc.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_size_t]
        cls.lib.test_crc.restype = ctypes.c_uint32
        cls.lib.bootloader_image_crc32.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t]
        cls.lib.bootloader_image_crc32.restype = ctypes.c_uint32
        cls.lib.test_sha.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p]
        cls.lib.test_sha_bitlen.argtypes = [ctypes.c_uint64, ctypes.c_uint32, ctypes.c_void_p]
        cls.lib.test_watchdog.argtypes = [ctypes.c_uint32, ctypes.c_uint32]

    def test_crc_streaming_and_unaligned_inputs(self):
        self.assertEqual(self.lib.test_crc(0, b'123456789', 9), 0xCBF43926)
        self.assertEqual(self.lib.test_crc(0, None, 0), 0)
        rng = random.Random(10)
        for length in [*range(130), 255, 256, 257, 4096, 40960]:
            data = rng.randbytes(length)
            seed = rng.getrandbits(32)
            buf = ctypes.create_string_buffer(b'\xff' + data)
            self.assertEqual(self.lib.test_crc(seed, ctypes.byref(buf, 1), length), zlib.crc32(data, seed))
            for split in {0, length // 2, length}:
                crc = self.lib.test_crc(seed, data[:split], split)
                self.assertEqual(self.lib.test_crc(crc, data[split:], length - split), zlib.crc32(data, seed))

    def test_masked_crc_partial_outside_and_wrapped_fields(self):
        maximum = ctypes.c_size_t(-1).value
        for length in [0, 1, 2, 3, 4, 9, 64, 257]:
            data = bytes((i * 37 + 3) & 255 for i in range(length))
            buf = ctypes.create_string_buffer(b'\xff' + data)
            for offset in [*range(length + 2), maximum - 4, maximum - 3, maximum - 2, maximum - 1, maximum]:
                # Match the original size_t interval, including overflow of offset + 4.
                end = (offset + 4) & maximum
                masked = bytes(0 if offset <= i < end else value for i, value in enumerate(data))
                self.assertEqual(self.lib.bootloader_image_crc32(ctypes.byref(buf, 1), length, offset),
                                 zlib.crc32(masked), (length, offset))

    def test_sha_padding_boundaries_and_chunking(self):
        rng = random.Random(11)
        for length in [*range(130), 255, 256, 257, 511, 512, 513, 4096]:
            data = rng.randbytes(length)
            buf = ctypes.create_string_buffer(b'\xff' + data)
            expected = hashlib.sha256(data).digest()
            for chunk in [1, 7, 55, 56, 63, 64, 65, 256]:
                out = ctypes.create_string_buffer(32)
                self.lib.test_sha(ctypes.byref(buf, 1), length, chunk, out)
                self.assertEqual(out.raw, expected, (length, chunk))
        data = b'a' * 1000000
        out = ctypes.create_string_buffer(32)
        self.lib.test_sha(data, len(data), 256, out)
        self.assertEqual(out.raw.hex(), 'cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0')

    def test_watchdog_running_and_every_channel_mask(self):
        for running in [0, 1]:
            for enabled in [*range(512), 0xFFFFFFFF]:
                self.assertEqual(self.lib.test_watchdog(running, enabled), 1, (running, enabled))

    def test_sha_64_bit_length_encoding(self):
        for previous in [0, 512, 2**32 - 512, 2**32, 2**63, 2**64 - 512, 2**64 - 8]:
            for tail in [0, 1, 55, 56, 63]:
                encoded = ctypes.create_string_buffer(8)
                self.lib.test_sha_bitlen(previous, tail, encoded)
                expected = (previous + tail * 8) % 2**64
                self.assertEqual(encoded.raw, expected.to_bytes(8, 'big'), (previous, tail))


if __name__ == '__main__':
    unittest.main()
