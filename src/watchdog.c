#include "watchdog.h"
#include "nrf.h"

__attribute__((noinline, noclone)) void otafix_watchdog_feed(void) {
  if (NRF_WDT->RUNSTATUS != 0) {
    uint32_t enabled = NRF_WDT->RREN & 0xFFu;
    while (enabled != 0) {
      NRF_WDT->RR[__builtin_ctz(enabled)] = WDT_RR_RR_Reload;
      enabled &= enabled - 1;
    }
  }
}
