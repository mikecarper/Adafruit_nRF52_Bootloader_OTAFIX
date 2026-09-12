#include "crc32.h"
#include "sha256.h"
#include "watchdog.h"
#include <string.h>

test_wdt_t test_wdt;

uint32_t test_crc(uint32_t previous, const uint8_t *data, size_t len) {
  return otafix_crc32_update(previous, data, len);
}

void test_sha(const uint8_t *data, size_t len, size_t chunk, uint8_t out[32]) {
  sha256_ctx_t c;
  sha256_init(&c);
  while (len) {
    const size_t n = len < chunk ? len : chunk;
    sha256_update(&c, data, n);
    data += n;
    len -= n;
  }
  sha256_final(&c, out);
}

void test_sha_bitlen(uint64_t previous, uint32_t tail, uint8_t encoded[8]) {
  sha256_ctx_t c;
  uint8_t digest[32];
  sha256_init(&c);
  c.bitlen = previous;
  c.datalen = tail;
  memset(c.data, 0xA5, sizeof(c.data));
  sha256_final(&c, digest);
  memcpy(encoded, c.data + 56, 8);
}

int test_watchdog(uint32_t running, uint32_t enabled) {
  test_wdt.RUNSTATUS = running;
  test_wdt.RREN = enabled;
  for (unsigned i = 0; i < 8; ++i) {
    test_wdt.RR[i] = 0xA5000000u + i;
  }
  otafix_watchdog_feed();
  for (unsigned i = 0; i < 8; ++i) {
    const uint32_t expected = running && (enabled & (1u << i)) ?
      WDT_RR_RR_Reload : 0xA5000000u + i;
    if (test_wdt.RR[i] != expected) {
      return 0;
    }
  }
  return test_wdt.RUNSTATUS == running && test_wdt.RREN == enabled;
}
