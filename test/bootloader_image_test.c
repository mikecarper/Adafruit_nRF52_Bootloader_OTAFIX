#include "usb/uf2/bootloader_image.h"

#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define IMAGE_START       0x000F4000UL
#define IMAGE_SIZE        0x0000A000UL
#define EXPECTED_BOARD_ID 0x239A0071UL
#define EXPECTED_DEVICE_NAME "T114_DFU"
#define FALSE_MANIFEST_OFFSET 0x00000200UL
#define MANIFEST_OFFSET   (IMAGE_SIZE - sizeof(bootloader_update_envelope_t))
#define TEST_BOOT_VERSION 0x0204010CUL

static _Alignas(uint32_t) uint8_t image[IMAGE_SIZE];
static const char expected_device_name[BOOTLOADER_UPDATE_DEVICE_NAME_SIZE] =
  EXPECTED_DEVICE_NAME;
static const char wrong_device_name[BOOTLOADER_UPDATE_DEVICE_NAME_SIZE] =
  "T096_DFU";

static void write_u16(size_t offset, uint16_t value) {
  image[offset] = (uint8_t)value;
  image[offset + 1] = (uint8_t)(value >> 8);
}

static void write_u32(size_t offset, uint32_t value) {
  image[offset] = (uint8_t)value;
  image[offset + 1] = (uint8_t)(value >> 8);
  image[offset + 2] = (uint8_t)(value >> 16);
  image[offset + 3] = (uint8_t)(value >> 24);
}

static void make_valid_image(void) {
  memset(image, 0xFF, sizeof(image));
  write_u32(0, 0x20040000UL);
  write_u32(4, IMAGE_START + 0x101UL);

  // A compiler may emit the compared magic constants into a literal pool.
  // They are not valid headers and must not be mistaken for duplicates.
  write_u32(FALSE_MANIFEST_OFFSET, BOOTLOADER_UPDATE_MANIFEST_MAGIC0);
  write_u32(FALSE_MANIFEST_OFFSET + 4, BOOTLOADER_UPDATE_MANIFEST_MAGIC1);

  write_u32(MANIFEST_OFFSET, BOOTLOADER_UPDATE_MANIFEST_MAGIC0);
  write_u32(MANIFEST_OFFSET + 4, BOOTLOADER_UPDATE_MANIFEST_MAGIC1);
  write_u16(MANIFEST_OFFSET + 8, BOOTLOADER_UPDATE_MANIFEST_VERSION);
  write_u16(MANIFEST_OFFSET + 10, sizeof(bootloader_update_manifest_t));
  write_u32(MANIFEST_OFFSET + 12, IMAGE_START);
  write_u32(MANIFEST_OFFSET + 16, IMAGE_SIZE);
  write_u32(MANIFEST_OFFSET + 20, EXPECTED_BOARD_ID);
  memset(image + MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, device_name), 0,
         BOOTLOADER_UPDATE_DEVICE_NAME_SIZE);
  memcpy(image + MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, device_name),
         EXPECTED_DEVICE_NAME, sizeof(EXPECTED_DEVICE_NAME));
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32), 0);

  size_t const ext = MANIFEST_OFFSET + sizeof(bootloader_update_manifest_t);
  write_u32(ext + offsetof(bootloader_update_extension_t, magic0),
            BOOTLOADER_UPDATE_EXTENSION_MAGIC0);
  write_u32(ext + offsetof(bootloader_update_extension_t, magic1),
            BOOTLOADER_UPDATE_EXTENSION_MAGIC1);
  write_u16(ext + offsetof(bootloader_update_extension_t, version),
            BOOTLOADER_UPDATE_EXTENSION_VERSION);
  write_u16(ext + offsetof(bootloader_update_extension_t, header_size),
            sizeof(bootloader_update_extension_t));
  write_u32(ext + offsetof(bootloader_update_extension_t, boot_version),
            TEST_BOOT_VERSION);
  write_u16(ext + offsetof(bootloader_update_extension_t, softdevice_family), 140u);
  write_u16(ext + offsetof(bootloader_update_extension_t, softdevice_fwid), 0x00B6u);
  write_u32(ext + offsetof(bootloader_update_extension_t, app_base), 0x00026000u);
  write_u16(ext + offsetof(bootloader_update_extension_t, layout_abi),
            BOOTLOADER_UPDATE_LAYOUT_ABI);
  write_u16(ext + offsetof(bootloader_update_extension_t, compat_flags), 0u);
  write_u32(ext + offsetof(bootloader_update_extension_t, reserved), 0u);

  uint32_t const crc =
    bootloader_image_crc32(image, sizeof(image), MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32));
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32), crc);
}

int main(void) {
  uint8_t too_short[sizeof(bootloader_update_envelope_t) - 1u] = {0};
  assert(!bootloader_image_validate(too_short, IMAGE_START, sizeof(too_short),
                                    EXPECTED_BOARD_ID, expected_device_name));

  make_valid_image();
  bootloader_image_info_t info;
  assert(bootloader_image_info(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                               expected_device_name, &info));
  assert(info.boot_version == TEST_BOOT_VERSION && info.softdevice_family == 140u &&
         info.softdevice_fwid == 0x00B6u && info.app_base == 0x00026000u &&
         info.layout_abi == BOOTLOADER_UPDATE_LAYOUT_ABI);
  assert(bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                   expected_device_name));
  // Internal shared-slot packages place the raw payload at container+365.
  // Validation must not require an aligned base pointer.
  static uint8_t unaligned_storage[IMAGE_SIZE + 1U];
  memcpy(unaligned_storage + 1U, image, sizeof(image));
  assert(bootloader_image_validate(unaligned_storage + 1U, IMAGE_START, IMAGE_SIZE,
                                   EXPECTED_BOARD_ID, expected_device_name));

  image[1234] ^= 0x80;
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    expected_device_name));

  make_valid_image();
  write_u32(MANIFEST_OFFSET + 20, 0x239A0029UL);
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    expected_device_name));

  make_valid_image();
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    wrong_device_name));

  make_valid_image();
  image[MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, device_name) +
        sizeof(EXPECTED_DEVICE_NAME)] = 'X';
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32), 0);
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32),
            bootloader_image_crc32(image, sizeof(image),
                                   MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32)));
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    expected_device_name));

  make_valid_image();
  write_u32(MANIFEST_OFFSET, 0);
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    expected_device_name));

  // A self-consistent-looking envelope at any old/scanned location is not
  // authoritative. New BLM2 candidates must carry it in the final 76 bytes.
  make_valid_image();
  memcpy(image + FALSE_MANIFEST_OFFSET, image + MANIFEST_OFFSET,
         sizeof(bootloader_update_envelope_t));
  memset(image + MANIFEST_OFFSET, 0xFF, sizeof(bootloader_update_envelope_t));
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    expected_device_name));

  make_valid_image();
  write_u32(MANIFEST_OFFSET + sizeof(bootloader_update_manifest_t) +
            offsetof(bootloader_update_extension_t, magic1), 0u);
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    expected_device_name));

  make_valid_image();
  write_u32(MANIFEST_OFFSET + sizeof(bootloader_update_manifest_t) +
            offsetof(bootloader_update_extension_t, boot_version), 0x02040100u);
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32), 0u);
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32),
            bootloader_image_crc32(image, sizeof(image),
              MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32)));
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    expected_device_name));

  make_valid_image();
  write_u32(MANIFEST_OFFSET + sizeof(bootloader_update_manifest_t) +
            offsetof(bootloader_update_extension_t, boot_version), UINT32_MAX);
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32), 0u);
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32),
            bootloader_image_crc32(image, sizeof(image),
              MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32)));
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    expected_device_name));

  const size_t zero_u16_offsets[] = {
    offsetof(bootloader_update_extension_t, softdevice_family),
    offsetof(bootloader_update_extension_t, softdevice_fwid),
    offsetof(bootloader_update_extension_t, layout_abi),
  };
  for (size_t i = 0; i < sizeof(zero_u16_offsets) / sizeof(zero_u16_offsets[0]); i++) {
    make_valid_image();
    write_u16(MANIFEST_OFFSET + sizeof(bootloader_update_manifest_t) +
              zero_u16_offsets[i], 0u);
    write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32), 0u);
    write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32),
              bootloader_image_crc32(
                image, sizeof(image),
                MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32)));
    assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE,
                                      EXPECTED_BOARD_ID, expected_device_name));
  }
  make_valid_image();
  write_u32(MANIFEST_OFFSET + sizeof(bootloader_update_manifest_t) +
            offsetof(bootloader_update_extension_t, app_base), 0u);
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32), 0u);
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32),
            bootloader_image_crc32(
              image, sizeof(image),
              MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32)));
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE,
                                    EXPECTED_BOARD_ID, expected_device_name));

  // Local UF2 is the explicit migration/recovery path. Compatibility fields
  // must be present, but nonzero values may deliberately differ from the
  // currently installed SoftDevice/application layout.
  make_valid_image();
  size_t const recovery_ext = MANIFEST_OFFSET + sizeof(bootloader_update_manifest_t);
  write_u16(recovery_ext + offsetof(bootloader_update_extension_t, softdevice_family), 132u);
  write_u16(recovery_ext + offsetof(bootloader_update_extension_t, softdevice_fwid), 0x1234u);
  write_u32(recovery_ext + offsetof(bootloader_update_extension_t, app_base), 0x00027000u);
  write_u16(recovery_ext + offsetof(bootloader_update_extension_t, layout_abi), 2u);
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32), 0u);
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32),
            bootloader_image_crc32(
              image, sizeof(image),
              MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32)));
  assert(bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE,
                                   EXPECTED_BOARD_ID, expected_device_name));

  make_valid_image();
  write_u32(0, 0xFFFFFFFFUL);
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    expected_device_name));

  make_valid_image();
  write_u32(4, IMAGE_START + IMAGE_SIZE + 1UL);
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    expected_device_name));

  // A complete decoy cannot override the fixed authoritative envelope.
  make_valid_image();
  memcpy(image + FALSE_MANIFEST_OFFSET, image + MANIFEST_OFFSET,
         sizeof(bootloader_update_envelope_t));
  write_u32(FALSE_MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32),
            0xA5A5A5A5UL);
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32), 0);
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32),
            bootloader_image_crc32(image, sizeof(image),
                                   MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32)));
  assert(bootloader_image_crc32(
           image, sizeof(image),
           FALSE_MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32)) !=
         0xA5A5A5A5UL);
  assert(bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                   expected_device_name));

  // BLMF ambiguity is base-first: a corrupt half-present extension beside a
  // second CRC-valid base identity cannot make that identity disappear. These
  // values are the coupled CRC fixed point for this deterministic fixture.
  make_valid_image();
  memcpy(image + FALSE_MANIFEST_OFFSET, image + MANIFEST_OFFSET,
         sizeof(bootloader_update_envelope_t));
  write_u32(FALSE_MANIFEST_OFFSET + sizeof(bootloader_update_manifest_t) +
              offsetof(bootloader_update_extension_t, magic1),
            0u);
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32),
            0x617D3284UL);
  write_u32(FALSE_MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32),
            0x58BA5E2EUL);
  assert(bootloader_image_crc32(
           image, sizeof(image),
           MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32)) ==
         0x617D3284UL);
  assert(bootloader_image_crc32(
           image, sizeof(image),
           FALSE_MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32)) ==
         0x58BA5E2EUL);
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE,
                                    EXPECTED_BOARD_ID, expected_device_name));

  // A CRC fixed point alone does not establish an identity when the declared
  // board or its canonical padded device name is structurally invalid.
  make_valid_image();
  memcpy(image + FALSE_MANIFEST_OFFSET, image + MANIFEST_OFFSET,
         sizeof(bootloader_update_manifest_t));
  write_u32(FALSE_MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, board_id), 0u);
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32),
            0x64EEF8EDUL);
  write_u32(FALSE_MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32),
            0xCEC92344UL);
  assert(bootloader_image_crc32(
           image, sizeof(image),
           MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32)) ==
         0x64EEF8EDUL);
  assert(bootloader_image_crc32(
           image, sizeof(image),
           FALSE_MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32)) ==
         0xCEC92344UL);
  assert(bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE,
                                   EXPECTED_BOARD_ID, expected_device_name));

  make_valid_image();
  memcpy(image + FALSE_MANIFEST_OFFSET, image + MANIFEST_OFFSET,
         sizeof(bootloader_update_manifest_t));
  image[FALSE_MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, device_name)] = ' ';
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32),
            0xDFB6BEC8UL);
  write_u32(FALSE_MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32),
            0xA7AC001BUL);
  assert(bootloader_image_crc32(
           image, sizeof(image),
           MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32)) ==
         0xDFB6BEC8UL);
  assert(bootloader_image_crc32(
           image, sizeof(image),
           FALSE_MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32)) ==
         0xA7AC001BUL);
  assert(bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE,
                                   EXPECTED_BOARD_ID, expected_device_name));

  puts("bootloader image validation: PASS");
  return 0;
}
