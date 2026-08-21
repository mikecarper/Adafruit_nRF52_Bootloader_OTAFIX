// Regression for Nordic SD_FWID_GET() base-address semantics. The FWID
// offset is relative to the SoftDevice, which begins after the MBR.
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static uint8_t simulated_flash[0x4000];

#define MBR_SIZE       0x1000u
#define SD_FWID_OFFSET 0x200Cu
#define SD_FWID_GET(baseaddr)                                                   \
  ((uint16_t)simulated_flash[(baseaddr) + SD_FWID_OFFSET] |                    \
   ((uint16_t)simulated_flash[(baseaddr) + SD_FWID_OFFSET + 1u] << 8))

#include "ota_softdevice_fwid.h"

int main(void) {
  memset(simulated_flash, 0xFF, sizeof(simulated_flash));
  // Exact S140 6.1.1 values observed in the release HEX: the old zero-base
  // read sees an instruction halfword, while the MBR-relative read sees FWID.
  simulated_flash[SD_FWID_OFFSET] = 0x02u;
  simulated_flash[SD_FWID_OFFSET + 1u] = 0xE0u;
  simulated_flash[MBR_SIZE + SD_FWID_OFFSET] = 0xB6u;
  simulated_flash[MBR_SIZE + SD_FWID_OFFSET + 1u] = 0x00u;

  const uint16_t wrong = SD_FWID_GET(0u);
  const uint16_t actual = mota_runtime_softdevice_fwid_get();
  const int ok = wrong == 0xE002u && actual == 0x00B6u;
  printf("SoftDevice FWID zero-base=0x%04X MBR-base=0x%04X %s\n",
         wrong, actual, ok ? "PASS" : "FAIL");
  return ok ? 0 : 1;
}
