#!/usr/bin/env python3
"""Run the real bench sender against the real bootloader BLE adapter on the host."""
import asyncio
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import secure_dfu_ble_test as firmware

sys.path.insert(0, str(firmware.ROOT / 'tools'))
import otafix_secure_ble_dfu_test as uploader
from generate_secure_dfu_test import init_packet


class SecureDfuUploaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        firmware.SecureDfuBleTest.setUpClass()
        cls.addClassCleanup(firmware.SecureDfuBleTest.doClassCleanups)

    def run_resume(self, size, offset, executed, fault=None):
        board = firmware.SecureDfuBleTest()
        board.setUp()
        board.image = board.image[:size]
        board.dat = init_packet(board.image)
        board.begin()
        for start in range(0, offset, 4096):
            end = min(start + 4096, size)
            board.create(2, end - start)
            for at in range(start, min(end, offset), 244):
                board.write(4, board.image[at:min(at + 244, end, offset)])
            if end < offset or (end == offset and executed):
                # A final receipt can be queued but lost: never deliver it here.
                board.control(b'\x04', deliver=end < size)
        board.lib.test_ble_connection(False)
        self.assertEqual(board.lib.test_ble_activations(), 0)
        resumed_bytes = []
        controls = []
        final_attempts = []
        recovered_faults = ('miss_first_execute', 'miss_two_receipts', 'late_receipt',
                            'ack_then_write_error', 'ack_then_hung_write', 'write_error_then_late_ack')
        expect_failure = fault is not None and fault not in recovered_faults
        address = 'AA:BB:CC:DD:EE:FF'

        class Scanner:
            @staticmethod
            async def discover(**kwargs):
                device = types.SimpleNamespace(address=address, name='3401_DFU')
                adv = types.SimpleNamespace(local_name='3401_DFU', service_uuids=[uploader.SERVICE])
                return {address: (device, adv)}

        class Client:
            def __init__(self, device, disconnected_callback, **kwargs):
                self.on_disconnect = disconnected_callback
                self._backend = object()
                self.services = types.SimpleNamespace(get_characteristic=lambda _: types.SimpleNamespace(
                    max_write_without_response_size=244))
                self.is_connected = True
                self.selected = 0

            def drop_link(self):
                self.is_connected = False
                board.lib.test_ble_connection(False)
                self.on_disconnect(self)

            async def __aenter__(self):
                board.lib.test_ble_connection(True)
                return self

            async def __aexit__(self, *args):
                self.is_connected = False
                board.lib.test_ble_connection(False)

            async def start_notify(self, characteristic, callback):
                self.notify = callback
                board.write(3, b'\x01\x00')

            async def write_gatt_char(self, characteristic, data, response):
                if not self.is_connected:
                    raise ConnectionError('write attempted on a disconnected link')
                final_execute = False
                if characteristic == uploader.CONTROL:
                    controls.append(bytes(data))
                    if data[0] in (1, 6):
                        self.selected = data[1]
                    final_execute = (data == b'\x04' and self.selected == 2 and
                                     offset + sum(map(len, resumed_bytes)) == size)
                    if final_execute:
                        final_attempts.append(asyncio.get_running_loop().time())
                    if final_execute and fault == 'hung_final_write':
                        await asyncio.Event().wait()
                    if final_execute and fault == 'miss_first_execute' and len(final_attempts) == 1:
                        return
                    if final_execute and fault in ('reject_final_execute', 'reject_and_write_error'):
                        self.notify(None, b'\x60\x04\x08')
                        if fault == 'reject_and_write_error':
                            self.drop_link()
                            raise ConnectionError('ATT failed after EXECUTE rejection')
                        return
                    if final_execute and fault == 'before_final_execute':
                        self.drop_link()
                        raise ConnectionError('link lost before final DATA EXECUTE')
                    reply = board.write(2, data, deliver=False)
                    if final_execute and (fault == 'miss_all_receipts' or
                                          (fault == 'miss_two_receipts' and len(final_attempts) <= 2)):
                        return
                    if final_execute and fault == 'late_receipt':
                        if len(final_attempts) == 1:
                            def deliver_late():
                                self.notify(None, reply)
                                board.lib.test_ble_tx_complete(board.lib.test_ble_tx_pending())
                                self.drop_link()
                            asyncio.get_running_loop().call_later(
                                uploader.FINAL_EXECUTE_RETRY_INTERVAL * 1.5, deliver_late)
                        return
                    if final_execute and fault == 'lost_final_receipt':
                        # ATT write completed, but its DFU notification was lost.
                        self.drop_link()
                        return
                    if final_execute and fault in ('malformed_final_receipt', 'malformed_and_write_error'):
                        reply += b'\x00'
                    if final_execute and fault == 'write_error_then_late_ack':
                        board.lib.test_ble_tx_complete(board.lib.test_ble_tx_pending())
                        self.drop_link()
                        asyncio.get_running_loop().call_later(0.025, self.notify, None, reply)
                        raise ConnectionError('ATT failed before notification dispatch')
                else:
                    resumed_bytes.append(bytes(data))
                    reply = board.write(4, data, deliver=False)
                if reply:
                    self.notify(None, reply)
                    board.lib.test_ble_tx_complete(board.lib.test_ble_tx_pending())
                if (characteristic == uploader.DATA and fault == 'after_last_packet' and
                        offset + sum(map(len, resumed_bytes)) == size):
                    self.drop_link()
                if board.lib.test_ble_activations():
                    if fault != 'missing_final_disconnect':
                        self.drop_link()
                if final_execute and fault in ('ack_then_write_error', 'malformed_and_write_error'):
                    raise ConnectionError('ATT failed after notification dispatch')
                if final_execute and fault == 'ack_then_hung_write':
                    await asyncio.Event().wait()

        args = types.SimpleNamespace(package=Path('mock-package.zip'), sha256='mock',
                                     disconnect_at=None, address=address, packet_size=244)

        async def run():
            await asyncio.wait_for(uploader.run(args), timeout=2)

        original_wait_for = asyncio.wait_for

        async def bounded_wait(awaitable, timeout):
            # Exercise the real receipt/disconnect timeout paths quickly.
            return await original_wait_for(awaitable, 0.05 if fault and timeout in (20, 30) else timeout)

        with mock.patch.dict(sys.modules, bleak=types.SimpleNamespace(BleakClient=Client, BleakScanner=Scanner)), \
                mock.patch.object(uploader, 'package', return_value=(board.image, board.dat)), \
                mock.patch.object(uploader, 'FINAL_EXECUTE_TIMEOUT', 0.4), \
                mock.patch.object(uploader, 'FINAL_EXECUTE_RETRY_INTERVAL', 0.05), \
                mock.patch.object(asyncio, 'wait_for', side_effect=bounded_wait), \
                mock.patch.object(uploader, 'log') as log:
            if expect_failure:
                with self.assertRaises((RuntimeError, ConnectionError, TimeoutError)) as failure:
                    asyncio.run(run())
                self.assertFalse(any(call.args[0] == 'PASS' for call in log.call_args_list))
                if fault not in ('malformed_final_receipt', 'reject_final_execute', 'missing_final_disconnect',
                                 'malformed_and_write_error', 'reject_and_write_error'):
                    self.assertIn('final DATA EXECUTE was not confirmed', str(failure.exception))
                    self.assertEqual(log.call_args.args, ('UNCONFIRMED',))
                    self.assertFalse(log.call_args.kwargs['final_execute_confirmed'])
            else:
                asyncio.run(run())
                self.assertEqual(log.call_args.args, ('PASS',))
                self.assertTrue(log.call_args.kwargs['final_execute_confirmed'])
                self.assertTrue(log.call_args.kwargs['disconnect_observed'])
                self.assertNotIn('target_initiated_disconnect', log.call_args.kwargs)
        self.assertEqual(b''.join(resumed_bytes), board.image[offset:])
        if fault in ('miss_first_execute', 'late_receipt'):
            self.assertEqual(len(final_attempts), 2)
        elif fault == 'miss_two_receipts':
            self.assertEqual(len(final_attempts), 3)
        elif fault == 'miss_all_receipts':
            self.assertGreaterEqual(len(final_attempts), 2)
            self.assertLessEqual(len(final_attempts), 8)
            self.assertLess(final_attempts[-1] - final_attempts[0], 0.4)
        elif fault != 'after_last_packet':
            self.assertEqual(len(final_attempts), 1)
        if len(final_attempts) > 1:
            self.assertTrue(all(b - a >= 0.05 for a, b in zip(final_attempts, final_attempts[1:])))
        if expect_failure:
            executed_at_end = fault not in ('after_last_packet', 'before_final_execute',
                                            'hung_final_write', 'reject_final_execute', 'reject_and_write_error')
            self.assertEqual(board.lib.test_ble_completed(), executed_at_end)
            self.assertEqual(board.lib.test_ble_finishes(), int(executed_at_end))
            if fault not in ('malformed_final_receipt', 'missing_final_disconnect', 'malformed_and_write_error'):
                self.assertEqual(board.lib.test_ble_activations(), 0)
            # For a missed EXECUTE or lost receipt the same session can recover
            # by repeating just COMMAND/DATA selection and DATA EXECUTE.
            if fault in ('after_last_packet', 'before_final_execute', 'lost_final_receipt',
                         'miss_all_receipts', 'hung_final_write', 'reject_final_execute'):
                board.resume(size)
                board.control(b'\x04')
                self.assertTrue(board.lib.test_ble_completed())
                self.assertEqual(board.lib.test_ble_activations(), 1)
                self.assertEqual(board.lib.test_ble_begins(), 1)
                self.assertEqual(board.lib.test_ble_finishes(), 1)
            return
        self.assertTrue(board.lib.test_ble_completed())
        self.assertEqual(board.lib.test_ble_activations(), 1)
        self.assertEqual(board.lib.test_ble_begins(), 1)
        self.assertEqual(board.lib.test_ble_finishes(), 1)
        if offset == size and not fault:
            self.assertEqual(controls[-2:], [b'\x06\x02', b'\x04'])

    def test_short_final_object_not_yet_executed(self):
        self.run_resume(8704, 8704, False)

    def test_short_final_object_execute_receipt_lost(self):
        self.run_resume(8704, 8704, True)

    def test_full_final_object_not_yet_executed(self):
        self.run_resume(8192, 8192, False)

    def test_full_final_object_execute_receipt_lost(self):
        self.run_resume(8192, 8192, True)

    def test_intermediate_and_partial_offsets(self):
        for offset, executed in ((0, False), (123, False), (4096, False),
                                 (4096, True), (8192, True), (8703, False)):
            with self.subTest(offset=offset, executed=executed):
                self.run_resume(8704, offset, executed)

    def test_disconnect_after_last_packet_never_reports_pass(self):
        for size in (8192, 8704):
            with self.subTest(size=size):
                self.run_resume(size, 4096, True, 'after_last_packet')

    def test_disconnect_before_final_execute_never_reports_pass(self):
        self.run_resume(8704, 8192, True, 'before_final_execute')

    def test_missing_final_execute_receipt_never_reports_pass(self):
        self.run_resume(8704, 8192, True, 'lost_final_receipt')

    def test_malformed_final_execute_receipt_never_reports_pass(self):
        self.run_resume(8704, 8192, True, 'malformed_final_receipt')

    def test_missing_final_disconnect_never_reports_pass(self):
        self.run_resume(8704, 8192, True, 'missing_final_disconnect')

    def test_missed_execute_retries_without_resending_data(self):
        self.run_resume(8704, 8192, True, 'miss_first_execute')

    def test_missed_receipts_retry_without_reapplying_image(self):
        for offset in (8192, 8704):
            with self.subTest(offset=offset):
                self.run_resume(8704, offset, False, 'miss_two_receipts')

    def test_late_receipt_from_previous_attempt_confirms_transfer(self):
        self.run_resume(8704, 8192, True, 'late_receipt')

    def test_retry_deadline_leaves_unconfirmed(self):
        self.run_resume(8704, 8192, True, 'miss_all_receipts')

    def test_hung_gatt_write_obeys_deadline_without_overlapping_writes(self):
        self.run_resume(8704, 8192, True, 'hung_final_write')

    def test_execute_rejection_is_not_retried(self):
        self.run_resume(8704, 8192, True, 'reject_final_execute')

    def test_valid_ack_survives_gatt_write_error(self):
        self.run_resume(8704, 8192, True, 'ack_then_write_error')

    def test_valid_ack_completes_despite_hung_gatt_write(self):
        self.run_resume(8704, 8192, True, 'ack_then_hung_write')

    def test_late_ack_survives_prior_gatt_write_error(self):
        self.run_resume(8704, 8192, True, 'write_error_then_late_ack')

    def test_malformed_ack_cannot_override_gatt_write_error(self):
        self.run_resume(8704, 8192, True, 'malformed_and_write_error')

    def test_rejection_cannot_override_gatt_write_error(self):
        self.run_resume(8704, 8192, True, 'reject_and_write_error')

    def test_production_retry_policy(self):
        self.assertEqual(uploader.FINAL_EXECUTE_TIMEOUT, 30)
        self.assertEqual(uploader.FINAL_EXECUTE_RETRY_INTERVAL, 2)

    def test_nonfinal_execute_is_not_retried(self):
        async def run():
            client = types.SimpleNamespace(write_gatt_char=mock.AsyncMock())
            sender = uploader.Sender(client)
            sender.response = mock.AsyncMock(side_effect=TimeoutError)
            with self.assertRaises(TimeoutError):
                await sender.execute()
            client.write_gatt_char.assert_awaited_once_with(uploader.CONTROL, b'\x04', response=True)
        asyncio.run(run())

    def test_cancelling_final_execute_stops_receiver_and_retries(self):
        async def run():
            wrote = asyncio.Event()

            async def write(*args, **kwargs):
                wrote.set()

            client = types.SimpleNamespace(is_connected=True, write_gatt_char=mock.AsyncMock(side_effect=write))
            sender = uploader.Sender(client)
            task = asyncio.create_task(sender.execute(final=True))
            await wrote.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            client.write_gatt_char.assert_awaited_once()
            self.assertEqual(asyncio.all_tasks(), {asyncio.current_task()})
        with mock.patch.object(uploader, 'log') as log:
            asyncio.run(run())
            self.assertFalse(any(call.args[0] in ('PASS', 'UNCONFIRMED') for call in log.call_args_list))


if __name__ == '__main__':
    unittest.main(verbosity=2)
