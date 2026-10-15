#ifndef RAK_SPI_TEST_NRF_H
#define RAK_SPI_TEST_NRF_H
#include <stdint.h>
#define SPIM_FREQUENCY_FREQUENCY_M8 0x80000000u
#define SPIM_FREQUENCY_FREQUENCY_K250 0x04000000u
#define SPIM_ENABLE_ENABLE_Disabled 0u
#define SPIM_ENABLE_ENABLE_Enabled 7u
#define WDT_RR_RR_Reload 0x6E524635u
#define GPIO_PIN_CNF_DIR_Output 1u
#define GPIO_PIN_CNF_DIR_Pos 0u
#define GPIO_PIN_CNF_INPUT_Disconnect 1u
#define GPIO_PIN_CNF_INPUT_Connect 0u
#define GPIO_PIN_CNF_INPUT_Pos 1u
#define GPIO_PIN_CNF_PULL_Pullup 3u
#define GPIO_PIN_CNF_PULL_Pos 2u
#define GPIO_PIN_CNF_DRIVE_H0H1 3u
#define GPIO_PIN_CNF_DRIVE_Pos 8u
#ifdef __cplusplus
// Synchronous register hooks model EasyDMA completion at TASKS_START without
// threads or a source-only reimplementation of the transport loop.
void host_spi_start(void);
void host_memory_barrier(void);
void host_gpio_latch(uint32_t mask, bool high);
void host_gpio_config(void *reg, uint32_t value);
#define __DMB() host_memory_barrier()
struct HostStartRegister {
  uint32_t value = 0;
  HostStartRegister& operator=(uint32_t next) {
    value = next;
    if (next != 0u) host_spi_start();
    return *this;
  }
  operator uint32_t() const { return value; }
};
struct HostWatchdogReload {
  uint32_t value = 0, writes = 0;
  HostWatchdogReload& operator=(uint32_t next) { value = next; writes++; return *this; }
};
struct HostSpim {
  uint32_t ENABLE = 0, FREQUENCY = 0, CONFIG = 0, ORC = 0;
  struct { uint32_t SCK = 0, MOSI = 0, MISO = 0; } PSEL;
  struct { uint32_t PTR = 0, MAXCNT = 0; } TXD, RXD;
  uint32_t EVENTS_END = 0, TASKS_STOP = 0;
  HostStartRegister TASKS_START;
};
struct HostWatchdog {
  uint32_t RUNSTATUS = 0, RREN = 0;
  HostWatchdogReload RR[8];
};
struct HostPinConfig {
  uint32_t value = 0;
  HostPinConfig& operator=(uint32_t next) {
    value = next; host_gpio_config(this, next); return *this;
  }
  operator uint32_t() const { return value; }
};
struct HostGpioLatch {
  bool high;
  uint32_t value = 0;
  HostGpioLatch& operator=(uint32_t next) {
    value = next; host_gpio_latch(next, high); return *this;
  }
};
struct HostGpio {
  HostPinConfig PIN_CNF[32];
  HostGpioLatch OUTSET{true}, OUTCLR{false};
};
extern HostSpim host_spim;
extern HostWatchdog host_watchdog;
extern HostGpio host_gpio;
#define NRF_SPIM2 (&host_spim)
#define NRF_WDT (&host_watchdog)
#define NRF_P0 (&host_gpio)
#endif
#endif
