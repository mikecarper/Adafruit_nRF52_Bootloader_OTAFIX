#include "ota_qspi_wake.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char *load_source(void) {
  const char *paths[] = {"../src/ota_qspi.c", "src/ota_qspi.c"};
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

int main(void) {
  test_opcode_and_timing();
  test_wake_precedes_activation();
  puts("QSPI pre-activation wake: PASS");
  return 0;
}
