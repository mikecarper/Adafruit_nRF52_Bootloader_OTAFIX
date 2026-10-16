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
  check("X1 held button chooses bounded USB probe, not unconditional BLE",
        dfu_entry_single_button_route(false, false, false, true) == DFU_SINGLE_BUTTON_USB_PROBE);
  check("unheld button does not alter ordinary recovery policy",
        dfu_entry_single_button_route(false, false, false, false) == DFU_SINGLE_BUTTON_UNCHANGED);
  check("explicit BLE wins over USB presence and a held button",
        dfu_entry_single_button_route(true, false, false, true) == DFU_SINGLE_BUTTON_BLE);
  check("explicit serial or UF2 bypasses button probe",
        dfu_entry_single_button_route(false, true, false, true) == DFU_SINGLE_BUTTON_USB);
  check("double reset remains USB with a held button",
        dfu_entry_single_button_route(false, false, true, true) == DFU_SINGLE_BUTTON_USB);
  check("explicit BLE remains BLE across a simultaneous double reset",
        dfu_entry_single_button_route(true, false, true, true) == DFU_SINGLE_BUTTON_BLE);

  return failures ? 1 : 0;
}
