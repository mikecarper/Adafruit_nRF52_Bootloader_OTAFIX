#ifndef OTAFIX_WATCHDOG_H_
#define OTAFIX_WATCHDOG_H_

#include "nrf.h"

// Keep the inherited internal watchdog reload loop shared across flash,
// mOTA and external-storage paths. External watchdog cadence stays with each
// caller; it must not be slowed down or pulsed on every internal reload.
__attribute__((noinline, noclone, unused)) static void otafix_watchdog_feed(void) {
  if (NRF_WDT->RUNSTATUS != 0) {
    const uint32_t enabled = NRF_WDT->RREN & 0xFFu;
    for (uint8_t channel = 0; channel < 8; channel++) {
      if ((enabled & (1u << channel)) != 0) {
        NRF_WDT->RR[channel] = WDT_RR_RR_Reload;
      }
    }
  }
}

#endif // OTAFIX_WATCHDOG_H_
