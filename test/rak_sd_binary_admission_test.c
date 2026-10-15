// Optional qualification of actual linked RAK4631 bootloader bytes. Reuse the
// existing hardware-free adapter, but invoke the real admission predicates.
#define main synthetic_bootloader_mota_test_main
#include "bootloader_mota_test.c"
#undef main

int main(int argc, char **argv) {
  if (argc != 5) {
    fprintf(stderr, "usage: %s bootloader.bin expected_caps expected_info expected_metadata\n", argv[0]);
    return 2;
  }
  FILE *file = fopen(argv[1], "rb");
  uint8_t *allocation = malloc(MOTA_NRF52_BL_SIZE + 1u);
  if (!file || !allocation) {
    fprintf(stderr, "cannot open candidate or allocate fixture\n");
    if (file) fclose(file);
    free(allocation);
    return 2;
  }
  // Deliberately unaligned, matching the signed internal container's payload.
  uint8_t *image = allocation + 1u;
  const size_t length = fread(image, 1, MOTA_NRF52_BL_SIZE, file);
  const int extra = fgetc(file);
  fclose(file);
  if (length != MOTA_NRF52_BL_SIZE || extra != EOF) {
    fprintf(stderr, "candidate must be exactly %u bytes\n", MOTA_NRF52_BL_SIZE);
    free(allocation);
    return 2;
  }

  bootloader_image_info_t info = {0};
  const int caps_ok = boot_image_caps_valid(image) != 0;
  const int info_ok = bootloader_image_info(image, MOTA_NRF52_BL_START,
      MOTA_NRF52_BL_SIZE, TEST_BOARD_ID, TEST_DEVICE_NAME_FIELD, &info) != 0;
  reset_device();
  // Exercise the same combined metadata/capability route as the actual update,
  // not a second test implementation of its marker rules.
  const uint32_t address = TEST_RAW_START + 365u;
  memcpy(FLASH + address, image, MOTA_NRF52_BL_SIZE);
  struct mota_min manifest = {0};
  manifest.fw_version = info.boot_version;
  const int metadata_ok = boot_image_metadata_valid_at(address, &manifest) != 0;
  printf("caps=%d info=%d metadata=%d version=%08x fwid=%04x app=%08x\n",
      caps_ok, info_ok, metadata_ok, info.boot_version,
      info.softdevice_fwid, info.app_base);
  const int success = caps_ok == atoi(argv[2]) && info_ok == atoi(argv[3]) &&
                      metadata_ok == atoi(argv[4]);
  free(allocation);
  return success ? 0 : 1;
}
