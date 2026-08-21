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
#define MANIFEST_OFFSET   0x00008A00UL
#define SECOND_MANIFEST_OFFSET 0x00008B00UL

static _Alignas(uint32_t) uint8_t image[IMAGE_SIZE];

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

  uint32_t const crc =
    bootloader_image_crc32(image, sizeof(image), MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32));
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32), crc);
}

int main(void) {
  make_valid_image();
  assert(bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                   EXPECTED_DEVICE_NAME));

  image[1234] ^= 0x80;
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    EXPECTED_DEVICE_NAME));

  make_valid_image();
  write_u32(MANIFEST_OFFSET + 20, 0x239A0029UL);
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    EXPECTED_DEVICE_NAME));

  make_valid_image();
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    "T096_DFU"));

  make_valid_image();
  image[MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, device_name) +
        sizeof(EXPECTED_DEVICE_NAME)] = 'X';
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32), 0);
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32),
            bootloader_image_crc32(image, sizeof(image),
                                   MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32)));
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    EXPECTED_DEVICE_NAME));

  make_valid_image();
  write_u32(MANIFEST_OFFSET, 0);
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    EXPECTED_DEVICE_NAME));

  make_valid_image();
  write_u32(0, 0xFFFFFFFFUL);
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    EXPECTED_DEVICE_NAME));

  make_valid_image();
  write_u32(4, IMAGE_START + IMAGE_SIZE + 1UL);
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    EXPECTED_DEVICE_NAME));

  // A complete but corrupt decoy must not hide the valid manifest later in
  // the image. Recompute the real CRC after inserting the decoy so it remains
  // independently valid.
  make_valid_image();
  memcpy(image + FALSE_MANIFEST_OFFSET, image + MANIFEST_OFFSET,
         sizeof(bootloader_update_manifest_t));
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
                                   EXPECTED_DEVICE_NAME));

  // These are the coupled CRC fixed point for two otherwise identical valid
  // manifests in this deterministic fixture. Prove both CRCs are valid, then
  // require the validator to reject the ambiguous image.
  make_valid_image();
  memcpy(image + SECOND_MANIFEST_OFFSET, image + MANIFEST_OFFSET, sizeof(bootloader_update_manifest_t));
  write_u32(MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32),
            0xBE0E5D51UL);
  write_u32(SECOND_MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32),
            0x19D6F0F1UL);
  assert(bootloader_image_crc32(
           image, sizeof(image),
           MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32)) == 0xBE0E5D51UL);
  assert(bootloader_image_crc32(
           image, sizeof(image),
           SECOND_MANIFEST_OFFSET + offsetof(bootloader_update_manifest_t, crc32)) == 0x19D6F0F1UL);
  assert(!bootloader_image_validate(image, IMAGE_START, IMAGE_SIZE, EXPECTED_BOARD_ID,
                                    EXPECTED_DEVICE_NAME));

  puts("bootloader image validation: PASS");
  return 0;
}
