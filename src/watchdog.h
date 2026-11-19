#ifndef OTAFIX_WATCHDOG_H_
#define OTAFIX_WATCHDOG_H_

// Service any configured hardware watchdog, including one inherited from
// the application. The board's external watchdog has its own cadence.
void otafix_watchdog_feed(void);

#endif // OTAFIX_WATCHDOG_H_
