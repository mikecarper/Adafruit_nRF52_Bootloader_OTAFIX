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
EXT_MAGIC0 = 0x324D4C42
EXT_MAGIC1 = 0x54464F53
EXT_VERSION = 2
EXT_FORMAT = "<IIHHIHHIHHI"
EXT_SIZE = struct.calcsize(EXT_FORMAT)


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
        extension = struct.unpack(
            EXT_FORMAT, read_bytes(image, address + HEADER_SIZE, EXT_SIZE)
        )
        (ext_magic0, ext_magic1, ext_version, ext_size, boot_version,
         sd_family, sd_fwid, app_base, layout_abi, compat_flags,
         reserved) = extension
        if (
            magic0 == MAGIC0
            and magic1 == MAGIC1
            and version == VERSION
            and header_size == HEADER_SIZE
            and image_size > 0
            and image_size % 4 == 0
            and address == image_start + image_size - (HEADER_SIZE + EXT_SIZE)
            and name_end > 0
            and all(0x21 <= value <= 0x7E for value in device_name[:name_end])
            and all(value == 0 for value in device_name[name_end:])
            and ext_magic0 == EXT_MAGIC0
            and ext_magic1 == EXT_MAGIC1
            and ext_version == EXT_VERSION
            and ext_size == EXT_SIZE
            and boot_version not in (0, 0xFFFFFFFF)
            and boot_version & 0xFF
            and sd_family not in (0, 0xFFFF)
            and sd_fwid not in (0, 0xFFFF)
            and app_base != 0
            and app_base % 0x1000 == 0
            and layout_abi == 1
            and compat_flags == 0
            and reserved == 0
        ):
            matches.append((address, image_start, image_size,
                            device_name[:name_end].decode("ascii"), extension))

    if len(matches) != 1:
        raise ValueError(f"expected exactly one bootloader manifest, found {len(matches)}")

    return matches[0]


def patch_manifest(hex_path, bin_path=None):
    image = IntelHex(hex_path)
    (manifest_address, image_start, image_size, device_name,
     extension) = find_manifest(image)
    boot_version, sd_family, sd_fwid, app_base, layout_abi = (
        extension[4], extension[5], extension[6], extension[7], extension[8]
    )
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
        f"boot_version=0x{boot_version:08X}, sd=s{sd_family}/0x{sd_fwid:04X}, "
        f"app_base=0x{app_base:08X}, layout_abi={layout_abi}, crc32=0x{checksum:08X}"
    )


def verify_manifest(hex_path):
    image = IntelHex(hex_path)
    (manifest_address, image_start, image_size, device_name,
     extension) = find_manifest(image)
    binary = bytearray(image.tobinarray(start=image_start, size=image_size))
    checksum_offset = manifest_address - image_start + CRC_OFFSET
    stored_checksum = struct.unpack_from("<I", binary, checksum_offset)[0]
    binary[checksum_offset:checksum_offset + 4] = b"\0" * 4
    calculated_checksum = zlib.crc32(binary) & 0xFFFFFFFF
    if stored_checksum == 0 or stored_checksum != calculated_checksum:
        raise ValueError(
            f"invalid bootloader manifest CRC: stored=0x{stored_checksum:08X}, "
            f"calculated=0x{calculated_checksum:08X}"
        )
    boot_version = extension[4]
    print(
        f"Verified bootloader manifest at 0x{manifest_address:08X}: "
        f"device={device_name}, boot_version=0x{boot_version:08X}, "
        f"crc32=0x{stored_checksum:08X}"
    )
    return stored_checksum


def main():
    parser = argparse.ArgumentParser(description="Patch the CRC32 in an OTAFIX bootloader update manifest.")
    parser.add_argument("hex_file", help="bootloader Intel HEX file to patch in place")
    parser.add_argument("--bin-out", help="optional fixed-size bootloader-region binary output")
    parser.add_argument("--verify", action="store_true", help="verify the fixed manifest CRC without writing")
    args = parser.parse_args()
    if args.verify:
        if args.bin_out:
            parser.error("--verify cannot be combined with --bin-out")
        verify_manifest(args.hex_file)
    else:
        patch_manifest(args.hex_file, args.bin_out)


if __name__ == "__main__":
    main()
