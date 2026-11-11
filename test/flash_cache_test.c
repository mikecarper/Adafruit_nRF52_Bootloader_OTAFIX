// Exercise the production cache with flash addresses redirected to a host array.
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define CODE_PAGE_SIZE 4096u
#define BOOTLOADER_SETTINGS_ADDRESS 0xFF000u
#define NRFX_CEIL_DIV(value, divisor) (((value) + (divisor) - 1u) / (divisor))
#define PRINTF(...) ((void)0)
#define OTAFIX_WATCHDOG_H_
static void otafix_watchdog_feed(void) {}

static uint8_t flash_memory[3u * CODE_PAGE_SIZE];
static unsigned writes, erases;

static const void *flash_pointer(const void *pointer, size_t len) {
  uintptr_t const address = (uintptr_t)pointer;
  if (address < sizeof(flash_memory)) {
    assert(len <= sizeof(flash_memory) - address);
    return flash_memory + address;
  }
  return pointer;
}

static void *flash_memcpy(void *dst, const void *src, size_t len) {
  return memcpy(dst, flash_pointer(src, len), len);
}

static int flash_memcmp(const void *left, const void *right, size_t len) {
  return memcmp(flash_pointer(left, len), flash_pointer(right, len), len);
}

static void nrfx_nvmc_page_erase(uint32_t address) {
  assert(address + CODE_PAGE_SIZE <= sizeof(flash_memory));
  memset(flash_memory + address, 0xFF, CODE_PAGE_SIZE);
  erases++;
}

static void nrfx_nvmc_words_write(uint32_t address, const void *data, uint32_t words) {
  assert(address + 4u * words <= sizeof(flash_memory));
  memcpy(flash_memory + address, data, 4u * words);
  writes++;
}

static void nrfx_nvmc_word_write(uint32_t address, uint32_t value) {
  (void)address;
  (void)value;
  assert(!"unexpected settings write");
}

#define memcpy flash_memcpy
#define memcmp flash_memcmp
#include "../src/flash_nrf5x.c"
#undef memcpy
#undef memcmp

int main(void) {
  uint8_t data[512];
  for (size_t i = 0; i < sizeof(data); i++) {
    data[i] = (uint8_t)i;
  }
  memset(flash_memory, 0xFF, sizeof(flash_memory));

  // A new write must compare against pending RAM, without flushing or erasing.
  flash_nrf5x_write(256u, data, 256u, false);
  assert(flash_nrf5x_matches(256u, data, 256u));
  assert(writes == 0 && erases == 0 && flash_memory[256] == 0xFF);
  data[32] ^= 1;
  assert(!flash_nrf5x_matches(256u, data, 256u));
  data[32] ^= 1;
  assert(flash_nrf5x_matches(256u, data, 256u));

  // Crossing to a new page flushes the first; reads must handle either source.
  flash_nrf5x_write(CODE_PAGE_SIZE - 256u, data, sizeof(data), false);
  assert(flash_nrf5x_matches(CODE_PAGE_SIZE - 256u, data, 256u));
  assert(flash_nrf5x_matches(CODE_PAGE_SIZE, data + 256u, 256u));
  assert(!flash_nrf5x_matches(CODE_PAGE_SIZE - 256u, data, sizeof(data)));
  assert(writes == CODE_PAGE_SIZE / 256u && erases == 0);
  data[300] ^= 1;
  assert(!flash_nrf5x_matches(CODE_PAGE_SIZE, data + 256u, 256u));
  data[300] ^= 1;
  assert(flash_nrf5x_matches(256u, data, 256u));

  // A discarded cache must stop matching bytes that never reached flash.
  flash_nrf5x_discard();
  assert(!flash_nrf5x_matches(CODE_PAGE_SIZE, data + 256u, 256u));
  assert(!flash_nrf5x_matches(UINT32_MAX - 8u, data, 16u));
  assert(flash_nrf5x_matches(0, data, 0));
  puts("flash cache duplicate comparison: PASS");
  return 0;
}
