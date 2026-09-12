#ifndef SHARED_HELPERS_NRF_H_
#define SHARED_HELPERS_NRF_H_
#include <stdint.h>
typedef struct {
  volatile uint32_t RUNSTATUS;
  volatile uint32_t RREN;
  volatile uint32_t RR[8];
} test_wdt_t;
extern test_wdt_t test_wdt;
#define NRF_WDT (&test_wdt)
#define WDT_RR_RR_Reload 0x6E524635u
#endif
