#!/usr/bin/env python3
"""Build an unsigned, application-only Nordic Secure DFU ZIP for the RAK3401 lab profile.

No signing bypass: this profile explicitly does not implement a signature trust
policy. The mandatory SHA-256 binds resume metadata to the complete application.
The production Legacy DFU profile will not accept this package.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile

APP_BASE = 0x26000
APP_END = 0xEA000
HW_VERSION = 0x3401
SOFTDEVICE_FWID = 0xB6


def varint(value):
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError('protobuf value out of uint32 range')
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def scalar(field, value):
    return varint(field << 3) + varint(value)


def message(field, data):
    return varint((field << 3) | 2) + varint(len(data)) + data


def init_packet(image):
    size = len(image)
    if size < 8 or size & 3 or size > APP_END - APP_BASE:
        raise ValueError('application length is outside the RAK3401 layout')
    stack, reset = struct.unpack_from('<II', image)
    if not 0x20000000 < stack <= 0x20040000 or stack & 7:
        raise ValueError('invalid application stack vector')
    if not reset & 1 or not APP_BASE <= (reset & ~1) < APP_BASE + size:
        raise ValueError('invalid application reset vector')
    digest = hashlib.sha256(image).digest()
    hash_message = scalar(1, 3) + message(2, digest[::-1])
    init = (scalar(1, 1) + scalar(2, HW_VERSION) + message(3, varint(SOFTDEVICE_FWID))
            + scalar(4, 0) + scalar(7, size) + message(8, hash_message))
    return message(1, scalar(1, 1) + message(2, init))


def application_from(path):
    if path.suffix.lower() != '.zip':
        return path.read_bytes()
    # Reuse the strict Legacy package parser; never include an entire node backup.
    from otafix_legacy_ble_dfu import read_package
    package = read_package(path, hashlib.sha256(path.read_bytes()).hexdigest())
    if package.mode != 4:
        raise ValueError('input ZIP must contain only an application')
    return package.firmware


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application', type=Path, required=True,
                        help='application BIN or application-only Legacy DFU ZIP')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output already exists; choose a new filename')
    image = application_from(args.application)
    dat = init_packet(image)
    manifest = {'manifest': {'application': {'bin_file': 'application.bin',
                                             'dat_file': 'application.dat'}}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for name, content in (('application.bin', image), ('application.dat', dat),
                              ('manifest.json', json.dumps(manifest).encode())):
            entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(entry, content)
    print(json.dumps({'zip': str(args.output), 'application_size': len(image),
                      'application_sha256': hashlib.sha256(image).hexdigest(),
                      'init_size': len(dat),
                      'zip_sha256': hashlib.sha256(args.output.read_bytes()).hexdigest()}, indent=2))


if __name__ == '__main__':
    main()
