#ifndef OTAFIX_WATCHDOG_H_
#define OTAFIX_WATCHDOG_H_

#include <stdint.h>

// Configure and start the watchdog when the caller has confirmed it is idle.
void otafix_watchdog_start(uint32_t ticks);

// Service any configured hardware watchdog, including one inherited from
// the application. The board's external watchdog has its own cadence.
void otafix_watchdog_feed(void);

#endif // OTAFIX_WATCHDOG_H_
