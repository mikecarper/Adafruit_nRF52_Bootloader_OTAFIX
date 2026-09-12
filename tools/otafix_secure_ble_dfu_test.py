#!/usr/bin/env python3
"""Lab-only application upload/resume test for SECURE_DFU_RAK3401_TEST.

Requires an exact ZIP digest and BLE address. Does not enter DFU, reset a
device, modify bonds, or accept bootloader/SoftDevice packages. A prior physical
identity/bootloader check is required before running this bench sender.
"""
import argparse
import asyncio
import hashlib
import io
import json
from pathlib import Path
import struct
import time
import zipfile
import zlib

from generate_secure_dfu_test import init_packet

SERVICE = '0000fe59-0000-1000-8000-00805f9b34fb'
CONTROL = '8ec90001-f315-4f60-9fb8-838830daea50'
DATA = '8ec90002-f315-4f60-9fb8-838830daea50'
FINAL_EXECUTE_TIMEOUT = 30
FINAL_EXECUTE_RETRY_INTERVAL = 2


def log(event, **fields):
    print(json.dumps({'time': time.time(), 'event': event, **fields}), flush=True)


def unconfirmed(reason, **fields):
    log('UNCONFIRMED', reason=reason, final_execute_confirmed=False, **fields)
    raise RuntimeError(f'final DATA EXECUTE was not confirmed: {reason}; '
                       'resume the same package if still in DFU, otherwise verify the application')


def package(path, expected):
    blob = path.read_bytes()
    if len(blob) > 1100000 or hashlib.sha256(blob).hexdigest() != expected.lower():
        raise ValueError('ZIP length or SHA-256 mismatch')
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        infos = z.infolist()
        if len(infos) != 3 or {i.filename for i in infos} != {'manifest.json', 'application.bin', 'application.dat'}:
            raise ValueError('unexpected Secure DFU ZIP members')
        if any(i.file_size > 1000000 for i in infos):
            raise ValueError('ZIP member is too large')
        expected_manifest = {'manifest': {'application': {'bin_file': 'application.bin',
                                                         'dat_file': 'application.dat'}}}
        if json.loads(z.read('manifest.json')) != expected_manifest:
            raise ValueError('only the RAK3401 test application manifest is accepted')
        image, dat = z.read('application.bin'), z.read('application.dat')
        if dat != init_packet(image):
            raise ValueError('metadata is not bound to this exact RAK3401 application')
    return image, dat


class Sender:
    def __init__(self, client):
        self.client = client
        self.queue = asyncio.Queue(maxsize=64)
        self.packet_size = 20
        self.prn_count = 0

    def notification(self, _, data):
        self.queue.put_nowait(bytes(data))

    async def response(self, opcode, timeout=30):
        response = await asyncio.wait_for(self.queue.get(), timeout=timeout)
        if len(response) < 3 or response[:3] != bytes((0x60, opcode, 1)):
            raise RuntimeError(f'unexpected response for {opcode:02x}: {response.hex()}')
        return response[3:]

    async def control(self, data):
        await self.client.write_gatt_char(CONTROL, data, response=True)
        return await self.response(data[0])

    async def select(self, kind):
        data = await self.control(bytes((6, kind)))
        if len(data) != 12:
            raise RuntimeError('invalid SELECT response length')
        return struct.unpack('<III', data)

    async def create(self, kind, size):
        await self.control(bytes((1, kind)) + struct.pack('<I', size))
        self.prn_count = 0

    async def execute(self, *, final=False):
        if not final:
            if await self.control(b'\x04'):
                raise RuntimeError('invalid EXECUTE response length')
            return

        # Only the final DATA EXECUTE is retried. No subsequent object/command
        # can mistake a delayed duplicate EXECUTE receipt for its own response.
        # Keep one receiver alive across retries to accept a late valid receipt.
        receipt = asyncio.create_task(self.response(4, timeout=FINAL_EXECUTE_TIMEOUT))
        write = None
        attempts = 0
        try:
            # Includes GATT writes: a stalled ATT write must not extend the
            # overall deadline. Never overlap or retry an uncertain ATT write.
            async with asyncio.timeout(FINAL_EXECUTE_TIMEOUT):
                while self.client.is_connected and not receipt.done():
                    attempts += 1
                    log('FINAL_EXECUTE_ATTEMPT', attempt=attempts)
                    write = asyncio.create_task(self.client.write_gatt_char(CONTROL, b'\x04', response=True))
                    done, _ = await asyncio.wait({write, receipt}, return_when=asyncio.FIRST_COMPLETED)
                    if receipt in done:
                        # The protocol receipt is authoritative even if the ATT
                        # write fails or hangs as the peer activates/disconnects.
                        break
                    try:
                        await write
                    except Exception as exc:
                        log('FINAL_EXECUTE_WRITE_ERROR', error=str(exc), attempts=attempts)
                        # Never retry an uncertain ATT write. A receipt already
                        # in flight may still arrive within the original deadline.
                        break
                    await asyncio.wait({receipt}, timeout=FINAL_EXECUTE_RETRY_INTERVAL)
                # A receipt can still be queued for dispatch when the disconnect
                # callback runs. Allow it within the same deadline, but send no
                # more writes on a closed link and never infer success from it.
                if await receipt:
                    raise RuntimeError('invalid EXECUTE response length')
        except TimeoutError:
            unconfirmed(f'no valid receipt within {FINAL_EXECUTE_TIMEOUT:g} seconds', attempts=attempts)
        finally:
            tasks = [task for task in (receipt, write) if task is not None]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def check(self, image, offset, receipt=False):
        result = await self.response(3) if receipt else await self.control(b'\x03')
        expected = struct.pack('<II', offset, zlib.crc32(image[:offset]))
        if result != expected:
            raise RuntimeError(f'offset/CRC mismatch: received {result.hex()}, expected {expected.hex()}')

    async def initialize(self, dat):
        maximum, offset, crc = await self.select(1)
        if len(dat) > maximum:
            raise RuntimeError('command does not fit')
        if offset > len(dat) or crc != zlib.crc32(dat[:offset]):
            raise RuntimeError('another command is already staged; refusing to overwrite it')
        if offset == 0:
            await self.create(1, len(dat))
        await self.control(b'\x02\x00\x00')
        while offset < len(dat):
            chunk = dat[offset:offset + self.packet_size]
            await self.client.write_gatt_char(DATA, chunk, response=False)
            offset += len(chunk)
        await self.check(dat, len(dat))
        await self.execute()
        await self.control(b'\x02\x08\x00')
        self.prn_count = 0


async def run(args):
    from bleak import BleakClient, BleakScanner
    image, dat = package(args.package, args.sha256)
    if args.disconnect_at is not None and not 0 < args.disconnect_at < len(image):
        raise ValueError('disconnect offset must be inside the image')
    log('PACKAGE_VERIFIED', image_size=len(image), image_sha256=hashlib.sha256(image).hexdigest(),
        unsigned_lab_protocol=True)
    did_disconnect = False
    last_progress = -1
    expected_resume = None
    while True:
        found = await BleakScanner.discover(timeout=8, return_adv=True, adapter='hci0')
        matches = [(d, a) for d, a in found.values() if d.address.upper() == args.address.upper()]
        if len(matches) != 1:
            raise RuntimeError('exact target is not advertising')
        device, adv = matches[0]
        if (adv.local_name or device.name) != '3401_DFU' or SERVICE not in [u.lower() for u in adv.service_uuids]:
            raise RuntimeError('target is not the RAK3401 Secure DFU test profile')
        disconnected = asyncio.Event()
        async with BleakClient(device, disconnected_callback=lambda _: disconnected.set(), timeout=25) as client:
            sender = Sender(client)
            final_execute_confirmed = False
            await client.start_notify(CONTROL, sender.notification)
            # BlueZ may need explicit MTU acquisition to expose its real write
            # limit. This negotiates only; it never probes by sending oversized data.
            acquire = getattr(client._backend, '_acquire_mtu', None)
            if acquire is not None:
                await asyncio.wait_for(acquire(), timeout=10)
            sender.packet_size = min(args.packet_size, client.services.get_characteristic(DATA).max_write_without_response_size)
            if sender.packet_size < 1:
                raise RuntimeError('invalid write capacity')
            log('CONNECTED', packet_size=sender.packet_size)
            await sender.initialize(dat)
            maximum, offset, crc = await sender.select(2)
            if maximum != 4096 or offset > len(image) or crc != zlib.crc32(image[:offset]):
                raise RuntimeError('target resume offset/CRC does not match the chosen image')
            if expected_resume is not None and offset != expected_resume:
                raise RuntimeError(f'resume moved from {expected_resume} to {offset}')
            log('RESUME_VERIFIED' if expected_resume is not None else 'DATA_START', offset=offset, crc32=f'{crc:08X}')
            if offset and (offset % maximum == 0 or offset == len(image)):
                # A short final object also needs EXECUTE on resume, whether
                # it was never executed or its previous receipt was lost.
                await sender.execute(final=offset == len(image))
                final_execute_confirmed = offset == len(image)
            while offset < len(image):
                object_start = offset - offset % maximum
                object_end = min(object_start + maximum, len(image))
                if offset == object_start:
                    await sender.create(2, object_end - object_start)
                while offset < object_end:
                    end = min(offset + sender.packet_size, object_end)
                    if not did_disconnect and args.disconnect_at is not None and offset < args.disconnect_at <= end:
                        end = args.disconnect_at
                    await client.write_gatt_char(DATA, image[offset:end], response=False)
                    offset = end
                    sender.prn_count += 1
                    if sender.prn_count == 8:
                        await sender.check(image, offset, receipt=True)
                        sender.prn_count = 0
                    if not did_disconnect and offset == args.disconnect_at:
                        await sender.check(image, offset)
                        expected_resume = offset
                        did_disconnect = True
                        log('INTENTIONAL_LINK_DROP', offset=offset)
                        await client.disconnect()
                        break
                if not client.is_connected:
                    break
                await sender.check(image, offset)
                await sender.execute(final=offset == len(image))
                final_execute_confirmed = offset == len(image)
                progress = offset * 20 // len(image)
                if progress != last_progress:
                    log('PROGRESS', bytes=offset, percent=round(offset * 100 / len(image), 1))
                    last_progress = progress
            if offset == len(image):
                if not final_execute_confirmed:
                    unconfirmed('link lost before final EXECUTE confirmation')
                await asyncio.wait_for(disconnected.wait(), timeout=20)
                # Bleak reports link closure, not its cause or application boot.
                # PASS confirms the acknowledged DFU transfer; verify boot or
                # flash readback independently during hardware qualification.
                log('PASS', application_size=len(image), resumed_from=expected_resume,
                    final_execute_confirmed=True, disconnect_observed=True)
                return
        await asyncio.sleep(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--address', required=True)
    parser.add_argument('--disconnect-at', type=int)
    parser.add_argument('--packet-size', type=int, choices=(20, 244), default=244)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
