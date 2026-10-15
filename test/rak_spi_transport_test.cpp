// Compile the actual shared SPIM2/SD implementation with synchronous register
// hooks. No copy of its DMA chunk loop or timeout policy lives in this test.
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "nrf.h"

HostSpim host_spim;
HostWatchdog host_watchdog;
HostGpio host_gpio;
static uint8_t tx[1024], rx[1026]; // -no-pie keeps EasyDMA's 32-bit host pointers representable
static uint32_t starts, drops_on, clocks, chunks[32], barriers, external_feeds;
static uint32_t event_order, latch_order[48], config_order[48], first_clock;
static uint8_t levels[48], modes[48];
static bool all_ff;
static uint8_t last_command[6];
static uint32_t command_frames;
static uint8_t *host_dma_pointer(uint32_t address);

void host_memory_barrier(void) { barriers++; }
void host_gpio_latch(uint32_t mask, bool high) {
  for (uint32_t pin = 0; pin < 32u; pin++) {
    if ((mask & (1u << pin)) != 0u) {
      levels[pin] = high;
      latch_order[pin] = ++event_order;
    }
  }
}
void host_gpio_config(void *reg, uint32_t value) {
  auto pin = static_cast<HostPinConfig *>(reg) - host_gpio.PIN_CNF;
  assert(pin >= 0 && pin < 32);
  modes[pin] = (value & 1u) != 0u ? 2u : (value & 2u) != 0u ? 0u : 1u;
  config_order[pin] = ++event_order;
}
void host_spi_start(void) {
  starts++;
  if (!first_clock) first_clock = ++event_order;
  assert(starts <= 32u || all_ff);
  const uint32_t count = host_spim.TXD.MAXCNT > host_spim.RXD.MAXCNT
                           ? host_spim.TXD.MAXCNT : host_spim.RXD.MAXCNT;
  assert(count > 0u && count <= 255u);
  if (starts <= 32u) chunks[starts - 1u] = count;
  if (drops_on == starts) return;
  const uint8_t *input = host_dma_pointer(host_spim.TXD.PTR);
  uint8_t *output = host_dma_pointer(host_spim.RXD.PTR);
  if (host_spim.TXD.MAXCNT == 6u && levels[26] == 0u) {
    memcpy(last_command, input, sizeof(last_command));
    command_frames++;
  }
  for (uint32_t i = 0; i < count; i++) {
    // The absent-card case never interprets TX command bytes (which may be
    // stack buffers outside the host's 32-bit EasyDMA address model).
    uint8_t value = !all_ff && i < host_spim.TXD.MAXCNT ? input[i] : static_cast<uint8_t>(host_spim.ORC);
    if (i < host_spim.RXD.MAXCNT) output[i] = all_ff ? 0xFFu : value ^ 0x5Au;
    clocks++;
  }
  host_spim.EVENTS_END = 1u;
}
extern "C" void nrf_gpio_pin_set(uint32_t pin) {
  assert(pin < 48u); levels[pin] = 1; latch_order[pin] = ++event_order;
}
extern "C" void nrf_gpio_pin_clear(uint32_t pin) {
  assert(pin < 48u); levels[pin] = 0; latch_order[pin] = ++event_order;
}
extern "C" void nrf_gpio_cfg_output(uint32_t pin) {
  assert(pin < 48u); modes[pin] = 2; config_order[pin] = ++event_order;
}
extern "C" void nrf_gpio_cfg_input(uint32_t pin, uint32_t pull) {
  assert(pin < 48u && pull == 3u); modes[pin] = 1; config_order[pin] = ++event_order;
}
extern "C" void nrf_gpio_cfg_default(uint32_t pin) {
  assert(pin < 48u); modes[pin] = 0; config_order[pin] = ++event_order;
}
extern "C" void board_watchdog_feed(void) { external_feeds++; }
extern "C" void nrf_delay_us(uint32_t) {}
extern "C" void nrf_delay_ms(uint32_t) {}

#include "ota_sd_spi.c"

static uint8_t *host_dma_pointer(uint32_t address) {
  if (address == 0u) return nullptr;
  // The target has 32-bit addresses. Preserve real low-address host globals,
  // and restore the host stack's upper bits for RAM command frames on x86-64.
  const struct { const void *data; size_t size; } globals[] = {
    {tx, sizeof(tx)}, {rx, sizeof(rx)}, {&g_tx, sizeof(g_tx)},
    {&g_rx, sizeof(g_rx)}, {g_sector, sizeof(g_sector)}
  };
  for (const auto& object : globals) {
    uintptr_t start = reinterpret_cast<uintptr_t>(object.data);
    if (address >= start && address - start < object.size)
      return reinterpret_cast<uint8_t *>(static_cast<uintptr_t>(address));
  }
  uintptr_t stack = reinterpret_cast<uintptr_t>(&address);
  return reinterpret_cast<uint8_t *>((stack & ~static_cast<uintptr_t>(UINT32_MAX)) | address);
}

static void reset(void) {
  host_spim = HostSpim{};
  host_watchdog = HostWatchdog{};
  host_gpio = HostGpio{};
  host_watchdog.RUNSTATUS = 1u;
  host_watchdog.RREN = 5u;
  starts = drops_on = clocks = barriers = external_feeds = 0;
  event_order = first_clock = command_frames = 0;
  memset(last_command, 0, sizeof(last_command));
  all_ff = false;
  memset(chunks, 0, sizeof(chunks));
  memset(latch_order, 0, sizeof(latch_order));
  memset(config_order, 0, sizeof(config_order));
  memset(levels, 0, sizeof(levels));
  memset(modes, 0, sizeof(modes));
  memset(rx, 0xA5, sizeof(rx));
  for (unsigned i = 0; i < sizeof(tx); i++) tx[i] = static_cast<uint8_t>(i * 17u);
  assert(reinterpret_cast<uintptr_t>(tx) <= UINT32_MAX);
  assert(reinterpret_cast<uintptr_t>(rx) <= UINT32_MAX);
}

static void begin(void) {
  assert(ota_rak_spi_begin(26u, 3u, 30u, 29u, SPIM_FREQUENCY_FREQUENCY_K250));
}

int main(int argc, char **argv) {
  if (argc != 2) return 2;
  int scenario = atoi(argv[1]);
  reset();
  if (scenario == 0) {
    begin();
    assert(ota_rak_spi_healthy());
    assert(levels[26] == 1 && levels[3] == 0 && levels[30] == 1);
    assert(latch_order[26] < config_order[26] && latch_order[3] < config_order[3]);
    assert(latch_order[30] < config_order[30] && modes[29] == 1);
    assert(host_spim.PSEL.SCK == 3u && host_spim.PSEL.MOSI == 30u && host_spim.PSEL.MISO == 29u);
    assert(host_spim.FREQUENCY == SPIM_FREQUENCY_FREQUENCY_K250 && host_spim.ENABLE == 7u);
    assert(host_gpio.PIN_CNF[26] == 0x303u && host_gpio.PIN_CNF[3] == 0x303u &&
           host_gpio.PIN_CNF[30] == 0x303u && host_gpio.PIN_CNF[29] == 0x0Cu);
    assert(host_gpio.PIN_CNF[31] == 0x303u && levels[31] == 1u);
    ota_rak_spi_set_frequency(SPIM_FREQUENCY_FREQUENCY_M8);
    assert(host_spim.FREQUENCY == SPIM_FREQUENCY_FREQUENCY_M8 && host_spim.ENABLE == 7u);
    assert(starts == 0u);
  } else if (scenario == 1) {
    begin();
    assert(ota_rak_spi_transfer(tx, rx + 1u, 515u));
    assert(starts == 3u && chunks[0] == 255u && chunks[1] == 255u && chunks[2] == 5u);
    for (unsigned i = 0; i < 515u; i++) assert(rx[i + 1u] == static_cast<uint8_t>(tx[i] ^ 0x5Au));
    assert(rx[0] == 0xA5u && rx[516] == 0xA5u);
    assert(host_watchdog.RR[0].writes > 0 && host_watchdog.RR[2].writes > 0);
    assert(host_watchdog.RR[1].writes == 0 && host_watchdog.RR[7].writes == 0);
    // Production must order RAM writes before DMA and CPU reads after END.
    assert(barriers >= 6u);
  } else if (scenario == 2) {
    begin();
    assert(ota_rak_spi_transfer(NULL, rx + 1u, 512u));
    assert(starts == 3u && host_spim.TXD.MAXCNT == 0u && host_spim.TXD.PTR == 0u);
    for (unsigned i = 1; i <= 512u; i++) assert(rx[i] == (0xFFu ^ 0x5Au));
    assert(ota_rak_spi_transfer(tx, NULL, 512u));
    assert(starts == 6u && host_spim.RXD.MAXCNT == 0u && host_spim.RXD.PTR == 0u);
    uint32_t before = starts;
    assert(ota_rak_spi_transfer(NULL, NULL, 0u) && starts == before);
  } else if (scenario == 3) {
    begin();
    drops_on = 2u;
    assert(!ota_rak_spi_transfer(tx, rx + 1u, 515u));
    assert(starts == 2u && host_spim.TASKS_STOP == 1u && host_spim.ENABLE == 0u);
    assert(!ota_rak_spi_healthy());
    for (unsigned i = 0; i < 255u; i++) assert(rx[i + 1u] == static_cast<uint8_t>(tx[i] ^ 0x5Au));
    for (unsigned i = 256u; i <= 516u; i++) assert(rx[i] == 0xA5u);
    assert(!ota_rak_spi_transfer(tx, rx, 1u) && starts == 2u);
    assert(host_watchdog.RR[0].writes > 0u);
  } else if (scenario == 4) {
    begin();
    ota_rak_spi_select(true);
    assert(levels[26] == 0u);
    ota_rak_spi_release(false);
    assert(levels[26] == 1u && modes[26] == 0u && modes[3] == 0u && modes[30] == 0u && modes[29] == 0u);
    assert(host_spim.ENABLE == 0u && host_spim.PSEL.SCK == UINT32_MAX &&
           host_spim.PSEL.MOSI == UINT32_MAX && host_spim.PSEL.MISO == UINT32_MAX);
    begin();
    ota_rak_spi_release(true);
    assert(levels[26] == 1u && modes[26] == 2u && modes[3] == 0u && modes[30] == 0u && modes[29] == 0u);
    assert(!ota_rak_spi_healthy());
  } else if (scenario == 5) {
    begin();
    assert(ota_rak_spi_byte(0xABu) == static_cast<uint8_t>(0xABu ^ 0x5Au));
    drops_on = starts + 1u;
    assert(ota_rak_spi_byte(0xABu) == 0xFFu && !ota_rak_spi_healthy());
  } else if (scenario == 6) {
    all_ff = true; // Absent card still clocks, but never answers CMD0.
    assert(!ota_sd_init());
    assert(latch_order[31] != 0 && config_order[31] < first_clock && levels[31] == 1u);
    assert(starts > 0u && starts < 2000u);
    ota_sd_deinit();
    assert(host_spim.ENABLE == 0u && modes[26] == 0u && levels[31] == 1u);
  } else if (scenario == 7) {
    assert(!ota_rak_spi_begin(32u, 3u, 30u, 29u, SPIM_FREQUENCY_FREQUENCY_M8));
    assert(!ota_rak_spi_begin(26u, 35u, 30u, 29u, SPIM_FREQUENCY_FREQUENCY_M8));
    assert(!ota_rak_spi_begin(26u, 3u, 62u, 29u, SPIM_FREQUENCY_FREQUENCY_M8));
    assert(!ota_rak_spi_begin(26u, 3u, 30u, 61u, SPIM_FREQUENCY_FREQUENCY_M8));
    assert(!ota_rak_spi_healthy() && event_order == 0u && starts == 0u);
  } else if (scenario == 8) {
    begin();
    all_ff = true; // No card response is needed to inspect transmitted bytes.
    (void)command(0u, 0u, 0x95u);
    assert(command_frames == 1u && memcmp(last_command, "\x40\0\0\0\0\x95", 6u) == 0);
    (void)command(8u, 0x000001AAu, 0x87u);
    assert(command_frames == 2u && memcmp(last_command, "\x48\0\0\x01\xAA\x87", 6u) == 0);
    (void)command(17u, 0x12345678u, 0xA5u);
    assert(command_frames == 3u && memcmp(last_command, "\x51\x12\x34\x56\x78\xA5", 6u) == 0);
  } else return 2;
  printf("production RAK SPIM transport scenario %d: PASS\n", scenario);
  return 0;
}
