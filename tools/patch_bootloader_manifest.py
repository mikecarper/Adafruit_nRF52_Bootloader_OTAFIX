#!/usr/bin/env python3

import argparse
import struct
import zlib

from intelhex import IntelHex


MAGIC0 = 0x464D4C42
MAGIC1 = 0x31435243
VERSION = 1
DEVICE_NAME_SIZE = 16
HEADER_FORMAT = f"<IIHHIII{DEVICE_NAME_SIZE}sI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
CRC_OFFSET = struct.calcsize(f"<IIHHIII{DEVICE_NAME_SIZE}s")


def read_bytes(image, address, size):
    return bytes(image[address + offset] for offset in range(size))


def find_manifest(image):
    signature = struct.pack("<II", MAGIC0, MAGIC1)
    matches = []

    for address in image.addresses():
        if address % 4 != 0 or read_bytes(image, address, len(signature)) != signature:
            continue

        fields = struct.unpack(HEADER_FORMAT, read_bytes(image, address, HEADER_SIZE))
        magic0, magic1, version, header_size, image_start, image_size, _, device_name, _ = fields
        name_end = device_name.find(b"\0")
        if (
            magic0 == MAGIC0
            and magic1 == MAGIC1
            and version == VERSION
            and header_size == HEADER_SIZE
            and image_size > 0
            and image_size % 4 == 0
            and image_start <= address
            and address + HEADER_SIZE <= image_start + image_size
            and name_end > 0
            and all(0x20 <= value <= 0x7E for value in device_name[:name_end])
            and all(value == 0 for value in device_name[name_end:])
        ):
            matches.append((address, image_start, image_size, device_name[:name_end].decode("ascii")))

    if len(matches) != 1:
        raise ValueError(f"expected exactly one bootloader manifest, found {len(matches)}")

    return matches[0]


def patch_manifest(hex_path, bin_path=None):
    image = IntelHex(hex_path)
    manifest_address, image_start, image_size, device_name = find_manifest(image)
    binary = bytearray(image.tobinarray(start=image_start, size=image_size))
    checksum_offset = manifest_address - image_start + CRC_OFFSET
    binary[checksum_offset:checksum_offset + 4] = b"\0" * 4
    checksum = zlib.crc32(binary) & 0xFFFFFFFF
    checksum_bytes = struct.pack("<I", checksum)

    for offset, value in enumerate(checksum_bytes):
        image[manifest_address + CRC_OFFSET + offset] = value
        binary[checksum_offset + offset] = value

    image.write_hex_file(hex_path)
    if bin_path:
        with open(bin_path, "wb") as output:
            output.write(binary)

    print(
        f"Patched bootloader manifest at 0x{manifest_address:08X}: "
        f"start=0x{image_start:08X}, size={image_size}, device={device_name}, "
        f"crc32=0x{checksum:08X}"
    )


def main():
    parser = argparse.ArgumentParser(description="Patch the CRC32 in an OTAFIX bootloader update manifest.")
    parser.add_argument("hex_file", help="bootloader Intel HEX file to patch in place")
    parser.add_argument("--bin-out", help="optional fixed-size bootloader-region binary output")
    args = parser.parse_args()
    patch_manifest(args.hex_file, args.bin_out)


if __name__ == "__main__":
    main()
