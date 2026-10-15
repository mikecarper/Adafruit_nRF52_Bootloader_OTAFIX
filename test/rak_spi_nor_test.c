// Exercise the real combined-only NOR driver against a command-level SPI
// device, independently of the high-level ota_delta.c media mocks.
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ota_rak_spi.h"
#include "nrf.h"

#define CAPACITY (1u << 21)
static uint8_t memory[CAPACITY];
static uint8_t jedec[3];
static bool healthy, selected, awake, wel, never_wel, busy_forever;
static bool busy_after_program, corrupt_readback;
static uint32_t phase, address, opcode, commands[256];
static uint32_t begin_calls, release_calls, watchdog_calls, transfers, fail_transfer;
static uint32_t busy_reads, program_busy_reads, program_bytes, program_start;
static uint32_t cs_pin, sck_pin, mosi_pin, miso_pin, spi_frequency;
static uint32_t clock_order, latch_order[48], output_order[48], begin_order;
static uint64_t delayed_us;
static bool keep_cs;

bool ota_rak_spi_begin(uint8_t cs, uint8_t sck, uint8_t mosi, uint8_t miso, uint32_t frequency) {
  begin_calls++;
  begin_order = ++clock_order;
  cs_pin = cs; sck_pin = sck; mosi_pin = mosi; miso_pin = miso;
  spi_frequency = frequency;
  healthy = true;
  return true;
}
void ota_rak_spi_set_frequency(uint32_t frequency) { spi_frequency = frequency; }
bool ota_rak_spi_healthy(void) { return healthy; }
void ota_rak_spi_watchdog(void) { watchdog_calls++; }
void ota_rak_spi_release(bool keep) {
  assert(!selected);
  release_calls++;
  keep_cs = keep;
  healthy = false;
}
void ota_rak_spi_select(bool active) {
  if (active) {
    assert(!selected);
    selected = true;
    phase = address = opcode = 0;
  } else if (selected) {
    if (opcode == 0x02u && phase > 4u) {
      wel = false;
      busy_reads = program_busy_reads;
      if (busy_after_program) busy_forever = true;
    }
    selected = false;
  }
}
static uint8_t clock_byte(uint8_t value) {
  assert(selected);
  if (phase++ == 0u) {
    opcode = value;
    commands[opcode]++;
    assert(opcode == 0xABu || opcode == 0xB9u || opcode == 0x9Fu ||
           opcode == 0x05u || opcode == 0x0Bu || opcode == 0x06u || opcode == 0x02u);
    if (opcode == 0xABu) awake = true;
    if (opcode == 0xB9u) { assert(!busy_forever && busy_reads == 0); awake = false; }
    if (opcode == 0x06u && !never_wel) wel = true;
    return 0xFFu;
  }
  assert(awake);
  if (opcode == 0x9Fu) return phase >= 2u && phase <= 4u ? jedec[phase - 2u] : 0xFFu;
  if (opcode == 0x05u) {
    bool busy = busy_forever || busy_reads != 0;
    if (busy_reads) busy_reads--;
    return (busy ? 1u : 0u) | (wel ? 2u : 0u);
  }
  if (opcode == 0x0Bu || opcode == 0x02u) {
    if (phase <= 4u) { address = (address << 8) | value; return 0xFFu; }
    if (opcode == 0x0Bu && phase == 5u) return 0xFFu; // FASTREAD dummy
    assert(address < CAPACITY);
    if (opcode == 0x02u) {
      assert(wel);
      if (program_bytes == 0u) program_start = address;
      program_bytes++;
      memory[address++] &= value;
      return 0xFFu;
    }
    uint8_t result = memory[address++];
    return corrupt_readback && program_bytes != 0u ? result ^ 1u : result;
  }
  return 0xFFu;
}
bool ota_rak_spi_transfer(const void *tx, void *rx, uint32_t length) {
  transfers++;
  if (!healthy || (fail_transfer && transfers == fail_transfer)) { healthy = false; return false; }
  const uint8_t *input = tx;
  uint8_t *output = rx;
  for (uint32_t i = 0; i < length; i++) {
    uint8_t value = clock_byte(input ? input[i] : 0xFFu);
    if (output) output[i] = value;
  }
  return true;
}
uint8_t ota_rak_spi_byte(uint8_t value) {
  uint8_t result = 0xFF;
  (void)ota_rak_spi_transfer(&value, &result, 1u);
  return result;
}
void nrf_gpio_pin_set(uint32_t pin) { assert(pin < 48u); latch_order[pin] = ++clock_order; }
void nrf_gpio_pin_clear(uint32_t pin) { (void)pin; abort(); }
void nrf_gpio_cfg_output(uint32_t pin) { assert(pin < 48u); output_order[pin] = ++clock_order; }
void nrf_gpio_cfg_input(uint32_t pin, uint32_t pull) { (void)pin; (void)pull; abort(); }
void nrf_gpio_cfg_default(uint32_t pin) { (void)pin; abort(); }
void nrf_delay_us(uint32_t delay) { delayed_us += delay; }
void nrf_delay_ms(uint32_t delay) { delayed_us += (uint64_t)delay * 1000u; }
void board_watchdog_feed(void) {}

#include "ota_qspi.c"

static void reset(uint8_t marker) {
  ota_qspi_deinit();
  memset(memory, 0xFF, sizeof(memory));
  memset(commands, 0, sizeof(commands));
  memset(latch_order, 0, sizeof(latch_order));
  memset(output_order, 0, sizeof(output_order));
  jedec[0] = marker == GPREGRET2_OTA_STAGE_RAK15001 ? 0xC8u : 0xEFu;
  jedec[1] = 0x40u; jedec[2] = 0x15u;
  healthy = selected = awake = wel = never_wel = busy_forever = false;
  busy_after_program = corrupt_readback = keep_cs = false;
  begin_calls = release_calls = watchdog_calls = transfers = fail_transfer = 0;
  busy_reads = program_busy_reads = program_bytes = program_start = 0;
  clock_order = begin_order = 0;
  delayed_us = 0;
  ota_qspi_set_rak_source(marker);
}

int main(int argc, char **argv) {
  if (argc != 2) return 2;
  int scenario = atoi(argv[1]);
  reset(GPREGRET2_OTA_STAGE_QSPI);
  if (scenario == 0) {
    const uint8_t markers[] = {GPREGRET2_OTA_STAGE_QSPI, GPREGRET2_OTA_STAGE_RAK15001,
                               GPREGRET2_OTA_STAGE_HEADER_W25};
    for (unsigned i = 0; i < sizeof(markers); i++) {
      reset(markers[i]);
      assert(ota_qspi_init());
      assert(begin_calls == 1 && cs_pin == (i == 1u ? 26u : 31u));
      assert(sck_pin == (i == 2u ? 16u : 3u) && mosi_pin == (i == 2u ? 17u : 30u));
      assert(miso_pin == (i == 2u ? 15u : 29u) && spi_frequency == SPIM_FREQUENCY_FREQUENCY_M8);
      // Real shared-begin GPIO sequencing is exercised independently by the
      // register fixture; this mock validates only the driver's selected pins.
      assert(commands[0xAB] == 1 && commands[0x9F] == 1 && delayed_us >= 100u);
      assert(ota_qspi_capacity() == CAPACITY);
      assert(ota_qspi_init() && begin_calls == 1); // idempotent, no re-probe
      ota_qspi_deinit();
      assert(commands[0xB9] == 1 && release_calls == 1 && !keep_cs && !awake);
      assert(ota_qspi_capacity() == 0u);
    }
    reset(0xFFu);
    assert(!ota_qspi_init() && begin_calls == 0 && commands[0x9F] == 0);
  } else if (scenario == 1) {
    for (unsigned i = 0; i < 3u; i++) {
      reset(GPREGRET2_OTA_STAGE_QSPI);
      jedec[i] ^= 1u;
      assert(!ota_qspi_init() && ota_qspi_capacity() == 0u && release_calls == 1);
      assert(commands[0x02] == 0 && program_bytes == 0);
    }
  } else if (scenario == 2) {
    assert(ota_qspi_init());
    for (unsigned i = 0; i < CAPACITY; i++) memory[i] = (uint8_t)(i * 17u + i / 251u);
    uint8_t out[514]; memset(out, 0xA5, sizeof(out));
    assert(ota_qspi_read(253u, out + 1, 512u));
    assert(out[0] == 0xA5u && out[513] == 0xA5u && memcmp(out + 1, memory + 253, 512) == 0);
    uint32_t before = transfers;
    assert(!ota_qspi_read(CAPACITY - 2u, out, 3u));
    assert(!ota_qspi_read(UINT32_MAX, out, 2u));
    assert(!ota_qspi_read(0, NULL, 0));
    assert(ota_qspi_read(CAPACITY, out, 0));
    assert(transfers == before && commands[0x02] == 0);
  } else if (scenario == 3) {
    assert(ota_qspi_init());
    memset(memory + 200u, 0xA5, 8u);
    memcpy(memory + 201u, "APRV", 4u);
    uint8_t original[8], clear[4] = {0}; memcpy(original, memory + 200u, 8u);
    assert(ota_qspi_write(201u, clear, 4u));
    memset(original + 1u, 0, 4u);
    assert(memcmp(original, memory + 200u, 8u) == 0);
    assert(program_start == 201u && program_bytes == 4u && commands[0x06] == 1u && commands[0x02] == 1u);
  } else if (scenario == 4) {
    assert(ota_qspi_init());
    uint8_t data[8]; memset(data, 0xFF, sizeof(data));
    memset(memory + 201u, 0, 4u);
    assert(!ota_qspi_write(201u, data, 4u)); // cannot turn programmed zero into one
    const uint32_t bad_lengths[] = {0u, 1u, 3u, 5u, 8u, UINT32_MAX};
    for (unsigned i = 0; i < sizeof(bad_lengths) / sizeof(bad_lengths[0]); i++)
      assert(!ota_qspi_write(201u, data, bad_lengths[i]));
    assert(!ota_qspi_write(254u, data, 4u));
    assert(!ota_qspi_write(CAPACITY - 1u, data, 4u));
    assert(!ota_qspi_write(UINT32_MAX, data, 4u));
    assert(!ota_qspi_write(201u, NULL, 4u));
    assert(commands[0x06] == 0 && commands[0x02] == 0 && program_bytes == 0);
  } else if (scenario == 5) {
    busy_reads = 3u;
    assert(ota_qspi_init() && delayed_us >= 130u && watchdog_calls >= 4u);
    reset(GPREGRET2_OTA_STAGE_QSPI);
    busy_forever = true;
    assert(!ota_qspi_init() && release_calls == 1 && keep_cs);
    assert(commands[0x9F] == 0 && commands[0xB9] == 0 && commands[0x05] <= 1000000u);
    assert(delayed_us >= 5000000u && delayed_us <= 10000100u);
  } else if (scenario == 6) {
    assert(ota_qspi_init());
    never_wel = true;
    uint8_t clear[4] = {0};
    assert(!ota_qspi_write(201u, clear, 4u));
    assert(commands[0x06] == 1u && commands[0x02] == 0u && memory[201] == 0xFFu);
  } else if (scenario == 7) {
    assert(ota_qspi_init());
    busy_after_program = true;
    uint8_t clear[4] = {0};
    assert(!ota_qspi_write(201u, clear, 4u));
    assert(program_bytes == 4u && delayed_us >= 100000u && commands[0x05] <= 10002u);
    ota_qspi_deinit();
    assert(commands[0xB9] == 0u && keep_cs && release_calls == 1u);
  } else if (scenario == 8) {
    assert(ota_qspi_init());
    corrupt_readback = true;
    uint8_t clear[4] = {0};
    assert(!ota_qspi_write(201u, clear, 4u) && program_bytes == 4u);
  } else if (scenario == 9) {
    fail_transfer = 1u;
    assert(!ota_qspi_init() && release_calls == 1u && keep_cs && commands[0x02] == 0u);
    reset(GPREGRET2_OTA_STAGE_QSPI);
    assert(ota_qspi_init());
    fail_transfer = transfers + 1u;
    uint8_t out[4] = {0xA5, 0xA5, 0xA5, 0xA5};
    assert(!ota_qspi_read(201u, out, sizeof(out)) && memcmp(out, "\xA5\xA5\xA5\xA5", 4u) == 0);
    ota_qspi_deinit();
    assert(release_calls == 1u && keep_cs && commands[0xB9] == 0u);
  } else return 2;
  ota_qspi_deinit();
  printf("production RAK SPI NOR scenario %d: PASS\n", scenario);
  return 0;
}
