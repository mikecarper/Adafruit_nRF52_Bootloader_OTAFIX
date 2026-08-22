#include <stdint.h>
#include <stdio.h>

#include "dfu_entry.h"

static int failures;

static void check(const char *name, int condition) {
  printf("%s - %s\n", condition ? "PASS" : "FAIL", name);
  if (!condition) {
    failures++;
  }
}

int main(void) {
  check("direct-jump magic is B1", DFU_MAGIC_OTA_APPJUM == 0xB1u);
  check("reset-based OTA magic is A8", DFU_MAGIC_OTA_RESET == 0xA8u);
  check("direct-jump entry converts to reset-based OTA",
        dfu_entry_reset_magic(DFU_MAGIC_OTA_APPJUM) == DFU_MAGIC_OTA_RESET);
  check("reset-based entry does not reset again",
        dfu_entry_reset_magic(DFU_MAGIC_OTA_RESET) == DFU_MAGIC_OTA_RESET);
  check("serial entry remains unchanged", dfu_entry_reset_magic(0x4Eu) == 0x4Eu);
  check("UF2 entry remains unchanged", dfu_entry_reset_magic(0x57u) == 0x57u);
  check("normal boot remains unchanged", dfu_entry_reset_magic(0u) == 0u);

  return failures ? 1 : 0;
}
