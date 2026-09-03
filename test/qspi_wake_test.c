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
  char *select = init == NULL ? NULL : strstr(init, "select_qspi_pins(true);");
  char *activate = init == NULL ? NULL : strstr(init, "NRF_QSPI_TASK_ACTIVATE");
  assert(init != NULL && wake != NULL && awake != NULL && select != NULL &&
         activate != NULL);
  assert(wake < awake && awake < select && select < activate);
  assert(strstr(init, "custom_instruction(0xAB") == NULL);
  free(source);
}

static void test_switched_rail_release_guard(void) {
  char *source = load_source();
  char *init = strstr(source, "bool ota_qspi_init(void)");
  char *power_on = init == NULL ? NULL : strstr(init, "MOTA_QSPI_POWER_ACTIVE);");
  char *settle = power_on == NULL ? NULL : strstr(power_on, "nrf_delay_ms(2);");
  char *wake = settle == NULL ? NULL : strstr(settle, "wake_flash_gpio();");
  char *deinit = strstr(source, "void ota_qspi_deinit(void)");
  char *released = deinit == NULL ? NULL : strstr(deinit, "bool flash_released = !g_awake;");
  char *sleep = released == NULL ? NULL : strstr(released, "custom_instruction(QSPI_DPD_ENTER");
  char *power_guard = sleep == NULL ? NULL : strstr(sleep, "if (flash_released)");
  char *power_off = power_guard == NULL ? NULL : strstr(power_guard, "nrf_gpio_pin_write(MOTA_QSPI_POWER_PIN");

  assert(init != NULL && power_on != NULL && settle != NULL && wake != NULL);
  assert(power_on < settle && settle < wake);
  assert(deinit != NULL && released != NULL && sleep != NULL && power_guard != NULL && power_off != NULL);
  assert(released < sleep && sleep < power_guard && power_guard < power_off);
  assert(strstr(source, "g_powered") == NULL);
  assert(strstr(source, "g_power_off_safe") == NULL);
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

static void test_new_qspi_board_profiles(void) {
  char *techo = load_file("../src/boards/lilygo_techo_lite/board.h",
                          "src/boards/lilygo_techo_lite/board.h");
  char *techo_make = load_file("../src/boards/lilygo_techo_lite/board.mk",
                               "src/boards/lilygo_techo_lite/board.mk");
  char *techo_cmake = load_file("../src/boards/lilygo_techo_lite/board.cmake",
                                "src/boards/lilygo_techo_lite/board.cmake");
  char *pca = load_file("../src/boards/pca10056/board.h",
                        "src/boards/pca10056/board.h");
  char *pca_make = load_file("../src/boards/pca10056/board.mk",
                             "src/boards/pca10056/board.mk");
  char *pca_cmake = load_file("../src/boards/pca10056/board.cmake",
                              "src/boards/pca10056/board.cmake");

  assert(strstr(techo, "BUTTON_DFU     _PINNUM(0, 24)") != NULL);
  assert(strstr(techo, "BUTTON_DFU_OTA _PINNUM(0, 24)") != NULL);
  assert(strstr(techo, "MOTA_QSPI_POWER_PIN    PIN_LDO_ENABLE") != NULL);
  assert(strstr(techo, "MOTA_QSPI_POWER_ACTIVE 1") != NULL);
  assert(strstr(techo, "MOTA_QSPI_SCK_PIN      _PINNUM(0, 4)") != NULL);
  assert(strstr(techo, "MOTA_QSPI_CSN_PIN      _PINNUM(0, 12)") != NULL);
  assert(strstr(techo_make, "DEVICE_NAME='\"LTEL_DFU\"'") != NULL);
  assert(strstr(techo_make, "-DMOTA_QSPI_FLASH=1") != NULL);
  assert(strstr(techo_cmake, "set(DEVICE_NAME LTEL_DFU)") != NULL);
  assert(strstr(techo_cmake, "set(MOTA_QSPI_FLASH ON)") != NULL);

  assert(strstr(pca, "BUTTON_DFU     11") != NULL);
  assert(strstr(pca, "BUTTON_DFU_OTA 12") != NULL);
  assert(strstr(pca, "MOTA_QSPI_SCK_PIN            19") != NULL);
  assert(strstr(pca, "MOTA_QSPI_CSN_PIN            17") != NULL);
  assert(strstr(pca, "MOTA_QSPI_JEDEC_MANUFACTURER 0xC2u") != NULL);
  assert(strstr(pca, "MOTA_QSPI_JEDEC_MEMORY_TYPE  0x28u") != NULL);
  assert(strstr(pca, "MOTA_QSPI_JEDEC_CAPACITY     0x17u") != NULL);
  assert(strstr(pca_make, "DEVICE_NAME='\"N056_DFU\"'") != NULL);
  assert(strstr(pca_make, "-DMOTA_QSPI_FLASH=1") != NULL);
  assert(strstr(pca_cmake, "set(DEVICE_NAME N056_DFU)") != NULL);
  assert(strstr(pca_cmake, "set(MOTA_QSPI_FLASH ON)") != NULL);

  free(techo);
  free(techo_make);
  free(techo_cmake);
  free(pca);
  free(pca_make);
  free(pca_cmake);
}

int main(void) {
  test_opcode_and_timing();
  test_wake_precedes_activation();
  test_switched_rail_release_guard();
  test_aux_deselect_precedes_wake();
  test_rak_w25q16_profiles();
  test_new_qspi_board_profiles();
  puts("QSPI wake, switched-rail safety, and board profiles: PASS");
  return 0;
}
