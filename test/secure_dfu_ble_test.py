#!/usr/bin/env python3
"""Execute the production BLE adapter with real SDK event types and mocked hardware."""
import ctypes
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from generate_secure_dfu_test import init_packet


class SecureDfuBleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='otafix-secure-ble-')
        cls.addClassCleanup(cls.temp.cleanup)
        library = Path(cls.temp.name) / ('ble.dll' if os.name == 'nt' else 'ble.so')
        includes = ['test/secure_dfu_ble_stubs', 'src',
                    'lib/sdk11/components/ble/ble_services/ble_dfu',
                    'lib/sdk11/components/ble/common',
                    'lib/sdk11/components/libraries/bootloader_dfu',
                    'lib/sdk/components/libraries/util', 'lib/nrfx/mdk', 'src/cmsis/include',
                    'lib/softdevice/s140_nrf52_6.1.1/s140_nrf52_6.1.1_API/include',
                    'lib/softdevice/s140_nrf52_6.1.1/s140_nrf52_6.1.1_API/include/nrf52']
        sanitizers = ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-O1', '-g'] \
            if os.environ.get('SECURE_DFU_TEST_SANITIZE') == '1' else []
        subprocess.run([os.environ.get('CC', 'gcc'), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-Wno-pointer-to-int-cast', '-Wno-unused-variable',
                        '-DNRF52840_XXAA', '-DS140', '-DSVCALL_AS_NORMAL_FUNCTION',
                        '-DSECURE_DFU_HW_VERSION=0x3401',
                        '-DDFU_APP_DATA_RESERVED=0xA000', *sanitizers, '-shared', '-fPIC',
                        *['-I' + str(ROOT / path) for path in includes],
                        str(ROOT / 'test/secure_dfu_ble_host.c'), str(ROOT / 'src/secure_dfu.c'),
                        str(ROOT / 'src/sha256.c'), '-o', str(library)], check=True)
        cls.lib = ctypes.CDLL(str(library))
        if os.name == 'nt':
            import _ctypes
            cls.addClassCleanup(lambda: _ctypes.FreeLibrary(cls.lib._handle))
        cls.lib.test_ble_write.argtypes = [ctypes.c_uint16, ctypes.c_void_p, ctypes.c_size_t]
        cls.lib.test_ble_receipt.argtypes = [ctypes.c_void_p]
        cls.lib.test_ble_receipt.restype = ctypes.c_size_t
        cls.lib.test_ble_flash.restype = ctypes.c_void_p
        for name in ('test_ble_connection', 'test_ble_stall_flash'):
            getattr(cls.lib, name).argtypes = [ctypes.c_bool]
        for name in ('test_ble_failed', 'test_ble_completed'):
            getattr(cls.lib, name).restype = ctypes.c_bool

    def setUp(self):
        self.lib.test_ble_reset()
        self.image = struct.pack('<II', 0x20030000, 0x26009) + bytes(i % 251 for i in range(8696))
        self.dat = init_packet(self.image)
        self.connect()

    def connect(self):
        self.lib.test_ble_hvx_error(0)
        self.lib.test_ble_disconnect_on_flash(0)
        self.lib.test_ble_connection(True)
        self.write(3, b'\x01\x00')

    def write(self, handle, data, deliver=True):
        self.lib.test_ble_write(handle, data, len(data))
        self.assertEqual(self.lib.test_ble_fault(), 0)
        out = ctypes.create_string_buffer(15)
        n = self.lib.test_ble_receipt(out)
        if n and deliver:
            self.lib.test_ble_tx_complete(self.lib.test_ble_tx_pending())
        self.assertEqual(self.lib.test_ble_fault(), 0)
        return out.raw[:n]

    def control(self, data, status=1, deliver=True):
        response = self.write(2, data, deliver)
        self.assertEqual(response[:3], bytes((0x60, data[0], status)))
        return response[3:]

    def select(self, kind):
        return struct.unpack('<III', self.control(bytes((6, kind))))

    def create(self, kind, size, status=1):
        self.control(bytes((1, kind)) + struct.pack('<I', size), status)

    def begin(self):
        self.create(1, len(self.dat))
        self.write(4, self.dat)
        self.control(b'\x04')
        self.select(2)

    def stage(self, start, end):
        self.create(2, end - start)
        for offset in range(start, end, 244):
            self.write(4, self.image[offset:min(offset + 244, end)])

    def resume(self, offset):
        self.lib.test_ble_connection(False)
        self.connect()
        self.assertEqual(self.select(1), (256, len(self.dat), zlib.crc32(self.dat)))
        self.control(b'\x04')
        self.assertEqual(self.lib.test_ble_activations(), 0)
        self.assertEqual(self.select(2), (4096, offset, zlib.crc32(self.image[:offset])))

    def finish(self, start):
        for offset in range(start, len(self.image), 4096):
            self.stage(offset, min(offset + 4096, len(self.image)))
            self.control(b'\x04')
        self.assertTrue(self.lib.test_ble_completed())
        self.assertFalse(self.lib.test_ble_failed())
        self.assertEqual(self.lib.test_ble_activations(), 1)
        self.assertEqual(ctypes.string_at(self.lib.test_ble_flash(), len(self.image)), self.image)

    def test_disconnect_during_flash_preserves_committed_offset(self):
        for error in (0x3002, 13):  # BLE_ERROR_INVALID_CONN_HANDLE, NRF_ERROR_TIMEOUT
            with self.subTest(error=error):
                self.setUp()
                self.begin()
                self.stage(0, 4096)
                self.lib.test_ble_disconnect_on_flash(error)
                self.assertEqual(self.write(2, b'\x04'), b'')
                self.assertFalse(self.lib.test_ble_failed())
                self.assertEqual(self.lib.test_ble_tx_pending(), 0)
                self.resume(4096)
                self.finish(4096)
                self.assertEqual(self.lib.test_ble_begins(), 1)

    def test_lost_final_execute_receipt_waits_for_reexecuted_data_receipt(self):
        for error in (0x3002, 13):
            with self.subTest(error=error):
                self.setUp()
                self.begin()
                for start in (0, 4096):
                    self.stage(start, start + 4096)
                    self.control(b'\x04')
                self.stage(8192, len(self.image))
                self.lib.test_ble_disconnect_on_flash(error)
                self.assertEqual(self.write(2, b'\x04'), b'')
                self.assertTrue(self.lib.test_ble_completed())
                self.assertEqual(self.lib.test_ble_activations(), 0)
                self.resume(len(self.image))
                self.control(b'\x04', deliver=False)
                self.assertEqual(self.lib.test_ble_activations(), 0)
                self.lib.test_ble_tx_complete(1)
                self.assertEqual(self.lib.test_ble_activations(), 1)
                self.assertEqual(self.lib.test_ble_finishes(), 1)

    def test_partial_object_survives_lost_prn(self):
        self.begin()
        self.create(2, 4096)
        self.control(b'\x02\x01\x00')
        self.lib.test_ble_hvx_error(0x3002)
        self.assertEqual(self.write(4, self.image[:123]), b'')
        self.resume(123)
        self.control(b'\x02\x00\x00')
        for offset in range(123, 4096, 244):
            self.write(4, self.image[offset:min(offset + 244, 4096)])
        self.control(b'\x04')
        self.finish(4096)

    def test_notification_backpressure_retries_without_reset(self):
        self.control(b'\x06\x01', deliver=False)
        self.lib.test_ble_hvx_error(19)  # NRF_ERROR_RESOURCES
        self.assertEqual(self.write(2, b'\x06\x02'), b'')
        self.assertEqual(self.lib.test_ble_queued(), 1)
        self.lib.test_ble_hvx_error(0)
        self.lib.test_ble_tx_complete(1)
        self.assertEqual(self.lib.test_ble_queued(), 0)
        self.assertEqual(self.lib.test_ble_tx_pending(), 1)
        self.assertEqual(self.lib.test_ble_fault(), 0)
        self.assertFalse(self.lib.test_ble_failed())

    def test_first_receipt_retries_after_transient_block_without_tx_event(self):
        for error in (8, 0x3401, 17, 19):
            with self.subTest(error=error):
                self.setUp()
                self.lib.test_ble_hvx_error(error)
                self.assertEqual(self.write(2, b'\x06\x01'), b'')
                self.assertEqual(self.lib.test_ble_queued(), 1)
                self.assertEqual(self.lib.test_ble_tx_pending(), 0)
                self.lib.test_ble_hvx_error(0)
                for kind in range(3):
                    self.lib.test_ble_ready(kind)
                self.lib.test_ble_poll(100)
                out = ctypes.create_string_buffer(15)
                n = self.lib.test_ble_receipt(out)
                self.assertEqual(out.raw[:n], b'\x60\x06\x01' + struct.pack('<III', 256, 0, 0))
                self.assertEqual(self.lib.test_ble_queued(), 0)
                self.assertEqual(self.lib.test_ble_tx_pending(), 1)
                self.assertEqual(self.lib.test_ble_fault(), 0)

    def test_poll_is_rate_limited_and_handles_clock_wrap(self):
        self.lib.test_ble_set_clock(0xFFFFE0)
        self.lib.test_ble_hvx_error(8)
        self.write(2, b'\x06\x01')
        for _ in range(20):
            self.lib.test_ble_poll(0)
        self.assertEqual(self.lib.test_ble_hvx_calls(), 1)
        self.lib.test_ble_poll(100)
        self.assertEqual(self.lib.test_ble_hvx_calls(), 2)
        for _ in range(20):
            self.lib.test_ble_poll(0)
        self.assertEqual(self.lib.test_ble_hvx_calls(), 2)
        self.lib.test_ble_hvx_error(0)
        self.lib.test_ble_poll(100)
        self.assertEqual(self.lib.test_ble_hvx_calls(), 3)
        self.assertEqual(self.lib.test_ble_queued(), 0)
        # Nothing remains to send: polling must not duplicate the receipt.
        self.lib.test_ble_poll(1000)
        self.assertEqual(self.lib.test_ble_hvx_calls(), 3)

    def test_poll_does_not_send_after_disconnect_or_with_cccd_disabled(self):
        self.lib.test_ble_hvx_error(8)
        self.write(2, b'\x06\x01')
        self.write(3, b'\x00\x00')
        self.lib.test_ble_hvx_error(0)
        self.lib.test_ble_poll(100)
        self.assertEqual(self.lib.test_ble_hvx_calls(), 1)
        self.lib.test_ble_connection(False)
        self.lib.test_ble_poll(100)
        self.assertEqual(self.lib.test_ble_hvx_calls(), 1)
        self.connect()
        self.lib.test_ble_poll(100)
        self.assertEqual(self.lib.test_ble_hvx_calls(), 1)

    def test_retried_final_receipt_still_requires_tx_completion(self):
        self.begin()
        for start in (0, 4096):
            self.stage(start, start + 4096)
            self.control(b'\x04')
        self.stage(8192, len(self.image))
        self.lib.test_ble_hvx_error(8)
        self.assertEqual(self.write(2, b'\x04'), b'')
        self.assertTrue(self.lib.test_ble_completed())
        self.assertEqual(self.lib.test_ble_activations(), 0)
        self.lib.test_ble_hvx_error(0)
        self.lib.test_ble_poll(100)
        self.assertEqual(self.lib.test_ble_activations(), 0)
        self.lib.test_ble_tx_complete(1)
        self.assertEqual(self.lib.test_ble_activations(), 1)
        self.assertEqual(self.lib.test_ble_finishes(), 1)

    def test_queue_overflow_can_recover_on_reconnect(self):
        self.begin()
        self.create(2, 4096)
        self.write(4, self.image[:123])
        self.lib.test_ble_hvx_error(19)
        for _ in range(9):
            self.assertEqual(self.write(2, b'\x03'), b'')
        self.assertEqual(self.lib.test_ble_disconnect_requests(), 1)
        self.assertEqual(self.lib.test_ble_transport_closes(), 0)
        self.assertFalse(self.lib.test_ble_failed())
        self.resume(123)
        for offset in range(123, 4096, 244):
            self.write(4, self.image[offset:min(offset + 244, 4096)])
        self.control(b'\x04')
        self.finish(4096)
        self.assertEqual(self.lib.test_ble_begins(), 1)

    def test_overflow_blocks_same_link_resubscription_and_stale_completion(self):
        for final_already_queued in (False, True):
            with self.subTest(final_already_queued=final_already_queued):
                self.setUp()
                self.begin()
                for start in (0, 4096):
                    self.stage(start, start + 4096)
                    self.control(b'\x04')
                self.stage(8192, len(self.image))
                # Match the production SoftDevice's 12-notification queue.
                for _ in range(11 if final_already_queued else 12):
                    self.control(b'\x03', deliver=False)
                if final_already_queued:
                    self.control(b'\x04', deliver=False)
                self.lib.test_ble_hvx_error(19)
                if not final_already_queued:
                    self.write(2, b'\x04')
                for _ in range(9 if final_already_queued else 8):
                    self.write(2, b'\x03')
                self.assertEqual(self.lib.test_ble_disconnect_requests(), 1)
                self.assertEqual(self.lib.test_ble_transport_closes(), 0)
                self.assertEqual(self.lib.test_ble_tx_pending(), 12)
                self.assertTrue(self.lib.test_ble_completed())
                writes = self.lib.test_ble_writes()
                hvx_calls = self.lib.test_ble_hvx_calls()
                self.lib.test_ble_hvx_error(0)
                # These writes were queued before the asynchronous disconnect.
                # Re-subscribing must not revive this connection or its receipts.
                for handle, data in ((3, b'\x00\x00'), (3, b'\x01\x00'),
                                     (2, b'\x04'), (2, b'\x06\x01'),
                                     (2, b'\x01\x01' + struct.pack('<I', len(self.dat))),
                                     (4, b'X')):
                    self.assertEqual(self.write(handle, data), b'')
                self.lib.test_ble_poll(100)
                self.lib.test_ble_tx_complete(1)
                self.lib.test_ble_tx_complete(11)
                self.assertEqual(self.lib.test_ble_activations(), 0)
                self.assertEqual(self.lib.test_ble_hvx_calls(), hvx_calls)
                self.assertEqual(self.lib.test_ble_disconnect_requests(), 1)
                self.assertEqual(self.lib.test_ble_writes(), writes)
                self.assertEqual(self.lib.test_ble_begins(), 1)
                self.assertFalse(self.lib.test_ble_failed())
                self.lib.test_ble_connection(False)
                self.assertEqual(self.lib.test_ble_tx_pending(), 0)
                self.assertEqual(self.lib.test_ble_queued(), 0)
                self.assertEqual(self.write(3, b'\x01\x00'), b'')
                self.assertEqual(self.write(2, b'\x04'), b'')
                self.connect()
                self.assertEqual(self.select(1), (256, len(self.dat), zlib.crc32(self.dat)))
                self.control(b'\x04')
                self.assertEqual(self.lib.test_ble_activations(), 0)
                self.assertEqual(self.select(2), (4096, len(self.image), zlib.crc32(self.image)))
                self.control(b'\x04', deliver=False)
                self.assertEqual(self.lib.test_ble_activations(), 0)
                self.lib.test_ble_tx_complete(1)
                self.assertEqual(self.lib.test_ble_activations(), 1)
                self.assertEqual(self.lib.test_ble_finishes(), 1)
                self.assertEqual(self.lib.test_ble_writes(), writes)

    def test_overflow_tolerates_already_disconnecting_link(self):
        for error in (0, 8, 0x3002):
            with self.subTest(error=error):
                self.setUp()
                self.lib.test_ble_disconnect_result(error)
                self.lib.test_ble_hvx_error(19)
                for _ in range(9):
                    self.write(2, b'\x06\x01')
                self.assertEqual(self.lib.test_ble_disconnect_requests(), 1)
                self.assertEqual(self.lib.test_ble_transport_closes(), 0)
                self.lib.test_ble_hvx_error(0)
                self.assertEqual(self.write(3, b'\x01\x00'), b'')
                self.assertEqual(self.write(2, b'\x06\x01'), b'')
                self.lib.test_ble_poll(100)
                self.assertEqual(self.lib.test_ble_tx_pending(), 0)
                self.lib.test_ble_connection(False)
                self.connect()
                self.assertEqual(self.select(1), (256, 0, 0))
                self.begin()
                self.finish(0)

    def test_overflow_unexpected_disconnect_error_still_faults(self):
        self.lib.test_ble_disconnect_result(7)  # NRF_ERROR_INVALID_PARAM
        self.lib.test_ble_hvx_error(19)
        for _ in range(8):
            self.write(2, b'\x06\x01')
        self.lib.test_ble_write(2, b'\x06\x01', 2)
        self.assertEqual(self.lib.test_ble_disconnect_requests(), 1)
        self.assertEqual(self.lib.test_ble_fault(), 7)

    def test_flash_failure_remains_latched(self):
        self.begin()
        self.stage(0, 4096)
        self.lib.test_ble_flash_error(3)
        self.control(b'\x04', 10)
        self.lib.test_ble_connection(False)
        self.connect()
        self.assertEqual(self.write(4, b'X'), b'\x60\x08\x08')
        self.create(1, len(self.dat), 8)
        self.assertTrue(self.lib.test_ble_failed())
        self.assertEqual(self.lib.test_ble_activations(), 0)

    def test_flash_timeout_keeps_buffer_owned_until_reset(self):
        self.begin()
        self.stage(0, 4096)
        self.lib.test_ble_stall_flash(True)
        self.control(b'\x04', 10)
        self.assertGreaterEqual(self.lib.test_ble_watchdog_feeds(), 10000)
        self.create(1, len(self.dat), 8)
        self.create(2, 4096, 8)
        self.assertEqual(self.write(4, b'X' * 20), b'\x60\x08\x08')
        self.lib.test_ble_stall_flash(False)
        self.lib.test_ble_finish_pending()
        self.assertEqual(ctypes.string_at(self.lib.test_ble_flash(), 240), self.image[:240])
        self.control(b'\x04', 10)
        self.assertTrue(self.lib.test_ble_failed())
        self.assertEqual(self.lib.test_ble_activations(), 0)

    def test_unexpected_softdevice_error_still_faults(self):
        self.lib.test_ble_hvx_error(7)  # NRF_ERROR_INVALID_PARAM is a programming error.
        self.lib.test_ble_write(2, b'\x06\x01', 2)
        self.assertEqual(self.lib.test_ble_fault(), 7)


class SecureDfuDisconnectTest(unittest.TestCase):
    def test_main_loop_poll_is_after_event_processing_and_exit_checks(self):
        # Wiring guard supplements the executable poll tests above. The poll
        # must not be starved behind an expected incoming write/TX event.
        source = (ROOT / 'lib/sdk11/components/libraries/bootloader_dfu/bootloader.c').read_text()
        loop = source[source.index('static void wait_for_events(void)'):]
        loop = loop[:loop.index('bool bootloader_app_is_valid')]
        self.assertLess(loop.index('app_sched_execute();'), loop.index('dfu_transport_ble_poll();'))
        self.assertLess(loop.index('return;'), loop.index('dfu_transport_ble_poll();'))
        self.assertIn('#ifdef SECURE_DFU_TEST', loop)
        transport = (ROOT / 'lib/sdk11/components/libraries/bootloader_dfu/dfu_transport_ble.c').read_text()
        poll = transport[transport.index('void dfu_transport_ble_poll(void)'):]
        poll = poll[:poll.index('void dfu_secure_connection_policy')]
        self.assertIn('IS_CONNECTED()', poll)
        self.assertIn('!m_tear_down_in_progress', poll)
        self.assertIn('secure_dfu_ble_poll(&m_dfu)', poll)

    def test_disconnect_races_only_tolerated_by_secure_profile(self):
        # Execute the shared transport's actual close function and timeout case;
        # the full BLE harness above mocks this backend boundary.
        source = (ROOT / 'lib/sdk11/components/libraries/bootloader_dfu/dfu_transport_ble.c').read_text()
        close = source[source.index('uint32_t dfu_transport_ble_close()'):]
        close = close[:close.index('\n#ifdef CFG_DEBUG')]
        timeout = source[source.index('        case BLE_GATTS_EVT_TIMEOUT:'):]
        timeout = timeout[:timeout.index('        case BLE_GAP_EVT_ADV_SET_TERMINATED:')]
        prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include "nrf_error.h"
#include "ble_err.h"
#define BLE_HCI_REMOTE_USER_TERMINATED_CONNECTION 0x13
#define BLE_GATTS_EVT_TIMEOUT 1
#define BLE_GATT_TIMEOUT_SRC_PROTOCOL 0
#define IS_CONNECTED() 1
#define APP_ERROR_CHECK(error) do { fault = (error); } while (0)
static uint16_t m_conn_handle;
static bool m_tear_down_in_progress;
static uint32_t injected, fault;
static void restore_ble_connection_policy(void) {}
static void advertising_stop(void) {}
static uint32_t sd_ble_gap_disconnect(uint16_t handle, uint8_t reason) {
  (void)handle; (void)reason; return injected;
}
'''
        timeout_wrapper = r'''
static void handle_timeout(void) {
  struct { struct { struct { struct { struct { uint8_t src; } timeout; } params; }
           gatts_evt; } evt; } event = {0}, *p_ble_evt = &event;
  uint32_t err_code;
  switch (BLE_GATTS_EVT_TIMEOUT) {
'''
        main = r'''
int main(void) {
  const uint32_t errors[] = {NRF_SUCCESS, BLE_ERROR_INVALID_CONN_HANDLE,
                            NRF_ERROR_INVALID_STATE, NRF_ERROR_INVALID_PARAM};
  for (unsigned i = 0; i < 4; ++i) {
    injected = errors[i];
    uint32_t expected = injected;
#ifdef SECURE_DFU_TEST
    if (injected == BLE_ERROR_INVALID_CONN_HANDLE || injected == NRF_ERROR_INVALID_STATE)
      expected = NRF_SUCCESS;
#endif
    fault = 0;
    assert(dfu_transport_ble_close() == NRF_SUCCESS);
    assert(m_tear_down_in_progress && fault == expected);
    fault = 0;
    handle_timeout();
    assert(fault == expected);
  }
  return 0;
}
'''
        code = prefix + close + timeout_wrapper + timeout + '\n}}\n' + main
        sdk = ROOT / 'lib/softdevice/s140_nrf52_6.1.1/s140_nrf52_6.1.1_API/include'
        with tempfile.TemporaryDirectory(prefix='otafix-disconnect-') as directory:
            for secure in (False, True):
                with self.subTest(secure=secure):
                    binary = Path(directory) / ('disconnect.exe' if os.name == 'nt' else 'disconnect')
                    flags = ['-DSECURE_DFU_TEST'] if secure else []
                    subprocess.run([os.environ.get('CC', 'gcc'), '-std=c11', '-Wall', '-Wextra', '-Werror',
                                    *flags, '-I' + str(sdk), '-x', 'c', '-', '-o', str(binary)],
                                   input=code, text=True, check=True)
                    subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
