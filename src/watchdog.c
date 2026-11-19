#include "watchdog.h"
#include "nrf.h"

__attribute__((noinline, noclone)) void otafix_watchdog_start(uint32_t ticks) {
  NRF_WDT->CONFIG = WDT_CONFIG_SLEEP_Msk;
  NRF_WDT->CRV = ticks;
  NRF_WDT->RREN = WDT_RREN_RR0_Msk;
  NRF_WDT->TASKS_START = 1;
}

__attribute__((noinline, noclone)) void otafix_watchdog_feed(void) {
  if (NRF_WDT->RUNSTATUS != 0) {
    uint32_t enabled = NRF_WDT->RREN & 0xFFu;
    while (enabled != 0) {
      NRF_WDT->RR[__builtin_ctz(enabled)] = WDT_RR_RR_Reload;
      enabled &= enabled - 1;
    }
  }
}
