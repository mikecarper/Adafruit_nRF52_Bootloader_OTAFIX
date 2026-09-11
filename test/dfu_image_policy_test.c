#include "dfu_image_policy.h"

#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "nrf_error.h"
#include "usb/uf2/bootloader_image.h"

#define APP_BASE       0x00026000UL
#define SD_IMAGE_SIZE  0x00002100UL
#define BL_IMAGE_SIZE  DFU_BL_IMAGE_MAX_SIZE
#define BOARD_ID       0x239A0071UL
#define BOOT_VERSION   0x02040404UL
#define LEGACY_MANIFEST_OFFSET 0x00000200UL

static uint32_t runtime_app_base = APP_BASE;
static uint16_t runtime_fwid = 0x00B6U;
static uint8_t app_image[512];
static uint8_t sd_bl_image[SD_IMAGE_SIZE + BL_IMAGE_SIZE];

uint32_t dfu_policy_runtime_app_base(void) {
  return runtime_app_base;
}

uint16_t dfu_policy_runtime_softdevice_fwid(void) {
  return runtime_fwid;
}

static void write_u16(uint8_t* image, size_t offset, uint16_t value) {
  image[offset] = (uint8_t)value;
  image[offset + 1] = (uint8_t)(value >> 8);
}

static void write_u32(uint8_t* image, size_t offset, uint32_t value) {
  image[offset] = (uint8_t)value;
  image[offset + 1] = (uint8_t)(value >> 8);
  image[offset + 2] = (uint8_t)(value >> 16);
  image[offset + 3] = (uint8_t)(value >> 24);
}

static void make_app(void) {
  memset(app_image, 0xA5, sizeof(app_image));
  write_u32(app_image, 0, 0x20040000UL);
  write_u32(app_image, 4, APP_BASE + 0x101UL);
}

static void make_softdevice(uint16_t fwid, uint32_t app_base) {
  memset(sd_bl_image, 0xFF, SD_IMAGE_SIZE);
  write_u32(sd_bl_image, 0, 0x20040000UL);
  write_u32(sd_bl_image, 4, MBR_SIZE + 0x101UL);
  sd_bl_image[SD_INFO_STRUCT_SIZE_OFFSET] =
    SD_UNIQUE_STR_OFFSET + SD_UNIQUE_STR_SIZE - SOFTDEVICE_INFO_STRUCT_OFFSET;
  write_u32(sd_bl_image, SOFTDEVICE_INFO_STRUCT_OFFSET + sizeof(uint32_t),
            SD_MAGIC_NUMBER);
  write_u32(sd_bl_image, SD_SIZE_OFFSET, app_base);
  write_u16(sd_bl_image, SD_FWID_OFFSET, fwid);
  write_u32(sd_bl_image, SD_ID_OFFSET, MOTA_SOFTDEVICE_FAMILY);
}

static void seal_bootloader_manifest(uint8_t* image, size_t manifest_offset) {
  size_t const crc_offset =
    manifest_offset + offsetof(bootloader_update_manifest_t, crc32);
  write_u32(image, crc_offset, 0U);
  write_u32(image, crc_offset,
            bootloader_image_crc32(image, BL_IMAGE_SIZE, crc_offset));
}

static void make_bootloader(uint32_t boot_version, uint16_t fwid,
                            uint32_t app_base) {
  uint8_t* image = sd_bl_image + SD_IMAGE_SIZE;
  memset(image, 0xFF, BL_IMAGE_SIZE);
  write_u32(image, 0, 0x20040000UL);
  write_u32(image, 4, BOOTLOADER_REGION_START + 0x101UL);

  size_t const manifest_offset =
    BL_IMAGE_SIZE - sizeof(bootloader_update_envelope_t);
  bootloader_update_envelope_t envelope;
  memset(&envelope, 0, sizeof(envelope));
  envelope.manifest.magic0 = BOOTLOADER_UPDATE_MANIFEST_MAGIC0;
  envelope.manifest.magic1 = BOOTLOADER_UPDATE_MANIFEST_MAGIC1;
  envelope.manifest.version = BOOTLOADER_UPDATE_MANIFEST_VERSION;
  envelope.manifest.header_size = sizeof(envelope.manifest);
  envelope.manifest.image_start = BOOTLOADER_REGION_START;
  envelope.manifest.image_size = BL_IMAGE_SIZE;
  envelope.manifest.board_id = BOARD_ID;
  memcpy(envelope.manifest.device_name, DEVICE_NAME, sizeof(DEVICE_NAME));
  envelope.extension.magic0 = BOOTLOADER_UPDATE_EXTENSION_MAGIC0;
  envelope.extension.magic1 = BOOTLOADER_UPDATE_EXTENSION_MAGIC1;
  envelope.extension.version = BOOTLOADER_UPDATE_EXTENSION_VERSION;
  envelope.extension.header_size = sizeof(envelope.extension);
  envelope.extension.boot_version = boot_version;
  envelope.extension.softdevice_family = MOTA_SOFTDEVICE_FAMILY;
  envelope.extension.softdevice_fwid = fwid;
  envelope.extension.app_base = app_base;
  envelope.extension.layout_abi = BOOTLOADER_UPDATE_LAYOUT_ABI;
  memcpy(image + manifest_offset, &envelope, sizeof(envelope));
  seal_bootloader_manifest(image, manifest_offset);
}

static void make_legacy_bootloader(void) {
  uint8_t* image = sd_bl_image + SD_IMAGE_SIZE;
  size_t const manifest_offset =
    BL_IMAGE_SIZE - sizeof(bootloader_update_envelope_t);
  make_bootloader(BOOT_VERSION, runtime_fwid, runtime_app_base);
  memcpy(image + LEGACY_MANIFEST_OFFSET, image + manifest_offset,
         sizeof(bootloader_update_manifest_t));
  memset(image + manifest_offset, 0xFF, sizeof(bootloader_update_envelope_t));
  seal_bootloader_manifest(image, LEGACY_MANIFEST_OFFSET);
}

static dfu_start_packet_t start_packet(uint8_t mode, uint32_t sd_size,
                                       uint32_t bl_size, uint32_t app_size) {
  dfu_start_packet_t packet = {
    .dfu_update_mode = mode,
    .sd_image_size = sd_size,
    .bl_image_size = bl_size,
    .app_image_size = app_size,
  };
  return packet;
}

int main(void) {
  make_app();
  dfu_start_packet_t packet =
    start_packet(DFU_UPDATE_APP, 0, 0, sizeof(app_image));
  uint32_t declared_size = 0;
  assert(dfu_start_packet_validate(&packet, &declared_size) == NRF_SUCCESS);
  assert(declared_size == sizeof(app_image));
  packet.dfu_update_mode = DFU_UPDATE_BL;
  assert(dfu_start_packet_validate(&packet, &declared_size) ==
         NRF_ERROR_NOT_SUPPORTED);
  packet = start_packet(DFU_UPDATE_APP, 0, 0, sizeof(app_image) - 1U);
  assert(dfu_start_packet_validate(&packet, &declared_size) ==
         NRF_ERROR_NOT_SUPPORTED);
  packet = start_packet(DFU_UPDATE_SD | DFU_UPDATE_BL, 0xFFFF6000UL,
                        DFU_BL_IMAGE_MAX_SIZE, 0);
  assert(dfu_start_packet_validate(&packet, &declared_size) ==
         NRF_ERROR_DATA_SIZE);

  packet = start_packet(DFU_UPDATE_APP, 0, 0, sizeof(app_image));
  assert(dfu_image_policy_validate(app_image, sizeof(app_image), &packet) ==
         NRF_SUCCESS);

  packet.dfu_update_mode = DFU_UPDATE_BL;
  assert(dfu_image_policy_validate(app_image, sizeof(app_image), &packet) ==
         NRF_ERROR_INVALID_DATA);
  packet = start_packet(DFU_UPDATE_APP, 0, 0, sizeof(app_image) - 1U);
  assert(dfu_image_policy_validate(app_image, sizeof(app_image), &packet) ==
         NRF_ERROR_INVALID_DATA);
  make_app();
  write_u32(app_image, 4, APP_BASE + sizeof(app_image) + 1U);
  packet = start_packet(DFU_UPDATE_APP, 0, 0, sizeof(app_image));
  assert(dfu_image_policy_validate(app_image, sizeof(app_image), &packet) ==
         NRF_ERROR_INVALID_DATA);

  make_softdevice(runtime_fwid, runtime_app_base);
  make_bootloader(BOOT_VERSION, runtime_fwid, runtime_app_base);
  packet = start_packet(DFU_UPDATE_SD | DFU_UPDATE_BL, SD_IMAGE_SIZE,
                        BL_IMAGE_SIZE, 0);
  assert(dfu_image_policy_validate(sd_bl_image, sizeof(sd_bl_image), &packet) ==
         NRF_SUCCESS);

  write_u32(sd_bl_image, 4, MBR_SIZE + SD_IMAGE_SIZE + 1U);
  assert(dfu_image_policy_validate(sd_bl_image, sizeof(sd_bl_image), &packet) ==
         NRF_ERROR_INVALID_DATA);
  make_softdevice(runtime_fwid, runtime_app_base);
  make_bootloader(BOOT_VERSION, runtime_fwid, runtime_app_base);

  // Authenticity and compatibility, not monotonic ordering, govern updates.
  // Compatible older, equal, and newer bootloaders are all intentional.
  make_bootloader(0x01000001UL, runtime_fwid, runtime_app_base);
  assert(dfu_image_policy_validate(sd_bl_image, sizeof(sd_bl_image), &packet) ==
         NRF_SUCCESS);
  make_bootloader(BOOT_VERSION, runtime_fwid, runtime_app_base);
  assert(dfu_image_policy_validate(sd_bl_image, sizeof(sd_bl_image), &packet) ==
         NRF_SUCCESS);
  make_bootloader(0x03000001UL, runtime_fwid, runtime_app_base);
  assert(dfu_image_policy_validate(sd_bl_image, sizeof(sd_bl_image), &packet) ==
         NRF_SUCCESS);

  // Remote policy accepts only genuinely historical relocated BLMF-only
  // images as legacy. A corrupt canonical BLM2 must not silently downgrade
  // its validation policy, even for a bootloader-only reinstall.
  make_legacy_bootloader();
  assert(dfu_image_policy_validate(sd_bl_image, sizeof(sd_bl_image), &packet) ==
         NRF_SUCCESS);
  uint8_t* bootloader = sd_bl_image + SD_IMAGE_SIZE;
  make_bootloader(BOOT_VERSION, runtime_fwid, runtime_app_base);
  size_t const manifest_offset =
    BL_IMAGE_SIZE - sizeof(bootloader_update_envelope_t);
  write_u32(bootloader,
            manifest_offset + sizeof(bootloader_update_manifest_t) +
              offsetof(bootloader_update_extension_t, magic1),
            0U);
  seal_bootloader_manifest(bootloader, manifest_offset);
  packet = start_packet(DFU_UPDATE_BL, 0, BL_IMAGE_SIZE, 0);
  assert(dfu_image_policy_validate(bootloader, BL_IMAGE_SIZE, &packet) ==
         NRF_ERROR_INVALID_DATA);

  make_legacy_bootloader();
  assert(dfu_image_policy_validate(bootloader, BL_IMAGE_SIZE, &packet) ==
         NRF_SUCCESS);
  packet = start_packet(DFU_UPDATE_SD | DFU_UPDATE_BL, SD_IMAGE_SIZE,
                        BL_IMAGE_SIZE, 0);

  make_bootloader(BOOT_VERSION, runtime_fwid + 1U, runtime_app_base);
  assert(dfu_image_policy_validate(sd_bl_image, sizeof(sd_bl_image), &packet) ==
         NRF_ERROR_INVALID_DATA);

  make_bootloader(BOOT_VERSION, runtime_fwid, runtime_app_base);
  sd_bl_image[SD_ID_OFFSET] ^= 1U;
  assert(dfu_image_policy_validate(sd_bl_image, sizeof(sd_bl_image), &packet) ==
         NRF_ERROR_INVALID_DATA);

  make_softdevice(runtime_fwid, runtime_app_base);
  make_bootloader(BOOT_VERSION, runtime_fwid, runtime_app_base);
  write_u32(sd_bl_image, SD_ID_OFFSET, 0x00010000UL | MOTA_SOFTDEVICE_FAMILY);
  assert(dfu_image_policy_validate(sd_bl_image, sizeof(sd_bl_image), &packet) ==
         NRF_ERROR_INVALID_DATA);

  make_softdevice(runtime_fwid, runtime_app_base + CODE_PAGE_SIZE);
  packet = start_packet(DFU_UPDATE_SD, SD_IMAGE_SIZE, 0, 0);
  assert(dfu_image_policy_validate(sd_bl_image, SD_IMAGE_SIZE, &packet) ==
         NRF_ERROR_INVALID_DATA);

  make_softdevice(runtime_fwid + 1U, runtime_app_base);
  assert(dfu_image_policy_validate(sd_bl_image, SD_IMAGE_SIZE, &packet) ==
         NRF_ERROR_INVALID_DATA);

  make_softdevice(runtime_fwid, runtime_app_base);
  assert(dfu_image_policy_validate(sd_bl_image, SD_IMAGE_SIZE, &packet) ==
         NRF_SUCCESS);

  make_softdevice(runtime_fwid, runtime_app_base);
  make_bootloader(BOOT_VERSION, runtime_fwid, runtime_app_base);
  packet = start_packet(DFU_UPDATE_SD | DFU_UPDATE_BL, SD_IMAGE_SIZE + 1U,
                        BL_IMAGE_SIZE - 1U, 0);
  assert(dfu_image_policy_validate(sd_bl_image, sizeof(sd_bl_image), &packet) ==
         NRF_ERROR_INVALID_DATA);

  size_t const board_offset =
    BL_IMAGE_SIZE - sizeof(bootloader_update_envelope_t) +
    offsetof(bootloader_update_manifest_t, board_id);
  write_u32(bootloader, board_offset, 0x239A0029UL);
  packet = start_packet(DFU_UPDATE_SD | DFU_UPDATE_BL, SD_IMAGE_SIZE,
                        BL_IMAGE_SIZE, 0);
  assert(dfu_image_policy_validate(sd_bl_image, sizeof(sd_bl_image), &packet) ==
         NRF_ERROR_INVALID_DATA);

  // A valid cross-board image is accepted only by the opt-in bridge. Test
  // both shared VID/PID but different name (GAT562/RAK4631) and different IDs.
  for (unsigned int shared_id = 0; shared_id < 2; shared_id++) {
    make_bootloader(BOOT_VERSION, runtime_fwid, runtime_app_base);
    write_u32(bootloader, board_offset, shared_id ? BOARD_ID : 0x239A0029UL);
    char const foreign_name[BOOTLOADER_UPDATE_DEVICE_NAME_SIZE] = "4631_DFU";
    memcpy(bootloader + manifest_offset + offsetof(bootloader_update_manifest_t, device_name),
           foreign_name, sizeof(foreign_name));
    seal_bootloader_manifest(bootloader, manifest_offset);
    uint32_t const expected_result = RECOVERY_ALLOW_ALL_BOARDS ? NRF_SUCCESS : NRF_ERROR_INVALID_DATA;
    packet = start_packet(DFU_UPDATE_SD | DFU_UPDATE_BL, SD_IMAGE_SIZE, BL_IMAGE_SIZE, 0);
    assert(dfu_image_policy_validate(sd_bl_image, sizeof(sd_bl_image), &packet) == expected_result);
    packet = start_packet(DFU_UPDATE_BL, 0, BL_IMAGE_SIZE, 0);
    assert(dfu_image_policy_validate(bootloader, BL_IMAGE_SIZE, &packet) == expected_result);

    // Valid CRC does not waive SoftDevice/layout metadata, even cross-board.
    size_t const extension_offset = manifest_offset + sizeof(bootloader_update_manifest_t);
    write_u16(bootloader, extension_offset + offsetof(bootloader_update_extension_t, softdevice_fwid),
              runtime_fwid + 1U);
    seal_bootloader_manifest(bootloader, manifest_offset);
    assert(dfu_image_policy_validate(bootloader, BL_IMAGE_SIZE, &packet) == NRF_ERROR_INVALID_DATA);
    write_u16(bootloader, extension_offset + offsetof(bootloader_update_extension_t, softdevice_fwid),
              runtime_fwid);
    write_u16(bootloader, extension_offset + offsetof(bootloader_update_extension_t, layout_abi),
              BOOTLOADER_UPDATE_LAYOUT_ABI + 1U);
    seal_bootloader_manifest(bootloader, manifest_offset);
    assert(dfu_image_policy_validate(bootloader, BL_IMAGE_SIZE, &packet) == NRF_ERROR_INVALID_DATA);
  }

  puts("Legacy DFU image policy: PASS");
  return 0;
}
