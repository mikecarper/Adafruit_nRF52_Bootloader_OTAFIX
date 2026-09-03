#include "ota_qspi_wake.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char *load_file(const char *from_test, const char *from_root) {
  const char *paths[] = {from_test, from_root};
  FILE *file = NULL;
  for (size_t i = 0; i < sizeof(paths) / sizeof(paths[0]); i++) {
    file = fopen(paths[i], "rb");
    if (file != NULL) {
      break;
    }
  }
  assert(file != NULL);
  assert(fseek(file, 0, SEEK_END) == 0);
  const long length = ftell(file);
  assert(length > 0 && fseek(file, 0, SEEK_SET) == 0);
  char *source = malloc((size_t)length + 1u);
  assert(source != NULL);
  assert(fread(source, 1, (size_t)length, file) == (size_t)length);
  source[length] = '\0';
  fclose(file);
  return source;
}

static char *load_source(void) {
  return load_file("../src/ota_qspi.c", "src/ota_qspi.c");
}

static void test_opcode_and_timing(void) {
  uint8_t command = 0;
  for (uint8_t bit = 0; bit < OTA_QSPI_WAKE_BITS; bit++) {
    command = (uint8_t)((command << 1) | ota_qspi_wake_bit(bit));
  }
  assert(OTA_QSPI_WAKE_BITS == 8u);
  assert(command == 0xABu);
  assert(OTA_QSPI_WAKE_EDGE_US > 0u);
  assert(OTA_QSPI_WAKE_GUARD_US >= 50u);
}

static void test_wake_precedes_activation(void) {
  char *source = load_source();
  char *init = strstr(source, "bool ota_qspi_init(void)");
  char *wake = init == NULL ? NULL : strstr(init, "wake_flash_gpio();");
  char *awake = init == NULL ? NULL : strstr(init, "g_awake = true;");
  char *unsafe = init == NULL ? NULL : strstr(init, "g_power_off_safe = false;");
  char *select = init == NULL ? NULL : strstr(init, "select_qspi_pins(true);");
  char *activate = init == NULL ? NULL : strstr(init, "NRF_QSPI_TASK_ACTIVATE");
  assert(init != NULL && wake != NULL && awake != NULL && unsafe != NULL &&
         select != NULL && activate != NULL);
  assert(wake < awake && wake < unsafe && awake < select && unsafe < select &&
         select < activate);
  assert(strstr(init, "custom_instruction(0xAB") == NULL);
  free(source);
}

static void test_aux_deselect_precedes_wake(void) {
  char *source = load_source();
  char *helper = strstr(source, "static void deselect_aux_device(void)");
  char *outset = helper == NULL ? NULL : strstr(helper, "->OUTSET");
  char *configure = helper == NULL ? NULL : strstr(helper, "->PIN_CNF");
  char *init = strstr(source, "bool ota_qspi_init(void)");
  char *deselect = init == NULL ? NULL : strstr(init, "deselect_aux_device();");
  char *wake = init == NULL ? NULL : strstr(init, "wake_flash_gpio();");
  assert(helper != NULL && outset != NULL && configure != NULL);
  assert(outset < configure);
  assert(init != NULL && deselect != NULL && wake != NULL && deselect < wake);
  assert(strstr(source, "QSPI_GPIO_PORT(MOTA_QSPI_AUX_CSN_PIN)->OUTCLR") == NULL);
  free(source);
}

static void test_rak_w25q16_profiles(void) {
  char *rak3401 = load_file(
    "../src/boards/wiscore_rak3401_rak13302_w25q16/board.h",
    "src/boards/wiscore_rak3401_rak13302_w25q16/board.h");
  char *rak3401_make = load_file(
    "../src/boards/wiscore_rak3401_rak13302_w25q16/board.mk",
    "src/boards/wiscore_rak3401_rak13302_w25q16/board.mk");
  char *rak3401_cmake = load_file(
    "../src/boards/wiscore_rak3401_rak13302_w25q16/board.cmake",
    "src/boards/wiscore_rak3401_rak13302_w25q16/board.cmake");
  char *rak4631 = load_file(
    "../src/boards/wiscore_rak4631_w25q16/board.h",
    "src/boards/wiscore_rak4631_w25q16/board.h");
  char *rak4631_make = load_file(
    "../src/boards/wiscore_rak4631_w25q16/board.mk",
    "src/boards/wiscore_rak4631_w25q16/board.mk");
  char *rak4631_cmake = load_file(
    "../src/boards/wiscore_rak4631_w25q16/board.cmake",
    "src/boards/wiscore_rak4631_w25q16/board.cmake");

  const char *common[] = {
    "MOTA_QSPI_SCK_PIN",
    "_PINNUM(0, 3)",
    "MOTA_QSPI_CSN_PIN",
    "_PINNUM(0, 31)",
    "MOTA_QSPI_IO0_PIN",
    "_PINNUM(0, 30)",
    "MOTA_QSPI_IO1_PIN",
    "_PINNUM(0, 29)",
    "MOTA_QSPI_IO2_PIN",
    "MOTA_QSPI_IO3_PIN",
    "MOTA_QSPI_SCK_FREQ",
    "NRF_QSPI_FREQ_32MDIV4",
    "MOTA_QSPI_JEDEC_MANUFACTURER 0xEFu",
    "MOTA_QSPI_JEDEC_MEMORY_TYPE  0x40u",
    "MOTA_QSPI_JEDEC_CAPACITY     0x15u",
  };
  for (size_t i = 0; i < sizeof(common) / sizeof(common[0]); i++) {
    assert(strstr(rak3401, common[i]) != NULL);
    assert(strstr(rak4631, common[i]) != NULL);
  }
  assert(strstr(rak3401, "MOTA_QSPI_AUX_CSN_PIN _PINNUM(0, 26)") != NULL);
  assert(strstr(rak4631, "MOTA_QSPI_AUX_CSN_PIN") == NULL);
  assert(strlen("3401_W25Q16_DFU") < 16u);
  assert(strstr(rak3401_make, "DEVICE_NAME='\"3401_W25Q16_DFU\"'") != NULL);
  assert(strstr(rak3401_make, "-DMOTA_QSPI_FLASH=1") != NULL);
  assert(strstr(rak3401_cmake, "set(DEVICE_NAME 3401_W25Q16_DFU)") != NULL);
  assert(strstr(rak3401_cmake, "set(MOTA_QSPI_FLASH ON)") != NULL);
  assert(strlen("4631_W25Q16_DFU") < 16u);
  assert(strstr(rak4631_make, "DEVICE_NAME='\"4631_W25Q16_DFU\"'") != NULL);
  assert(strstr(rak4631_make, "-DMOTA_QSPI_FLASH=1") != NULL);
  assert(strstr(rak4631_cmake, "set(DEVICE_NAME 4631_W25Q16_DFU)") != NULL);
  assert(strstr(rak4631_cmake, "set(MOTA_QSPI_FLASH ON)") != NULL);

  free(rak3401);
  free(rak3401_make);
  free(rak3401_cmake);
  free(rak4631);
  free(rak4631_make);
  free(rak4631_cmake);
}

int main(void) {
  test_opcode_and_timing();
  test_wake_precedes_activation();
  test_aux_deselect_precedes_wake();
  test_rak_w25q16_profiles();
  puts("QSPI pre-activation wake and shared-bus profiles: PASS");
  return 0;
}
