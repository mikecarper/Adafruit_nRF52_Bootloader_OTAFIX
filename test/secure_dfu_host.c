// Host adapter for the actual protocol core. No substitute state machine.
#include "secure_dfu.h"
#include "sha256.h"
#include <string.h>

static secure_dfu_t       state;
static secure_dfu_image_t expected;
static uint8_t            flash[10000];
static uint32_t           offset, begins, writes, finishes;
static bool               fail_write;

uint32_t secure_dfu_max_image(void) {
  return sizeof(flash);
}
uint16_t secure_dfu_fwid(void) {
  return 0xB6;
}
void secure_dfu_activity(void) {
}
bool secure_dfu_begin(const secure_dfu_image_t *image) {
  expected = *image;
  memset(flash, 0xFF, sizeof(flash));
  offset = 0;
  ++begins;
  return true;
}
bool secure_dfu_write(const uint32_t *data, uint32_t n) {
  if (fail_write || n > sizeof(flash) - offset) {
    return false;
  }
  memcpy(flash + offset, data, n);
  offset += n;
  ++writes;
  return true;
}
bool secure_dfu_finish(void) {
  uint8_t      hash[32];
  sha256_ctx_t sha;
  sha256_init(&sha);
  sha256_update(&sha, flash, offset);
  sha256_final(&sha, hash);
  ++finishes;
  return offset == expected.size && memcmp(hash, expected.sha256, 32) == 0;
}
void test_reset(void) {
  secure_dfu_init(&state);
  memset(flash, 0xA5, sizeof(flash));
  offset = begins = writes = finishes = 0;
  fail_write                          = false;
}
size_t test_control(const uint8_t *p, size_t n, uint8_t out[15]) {
  return secure_dfu_control(&state, p, n, out);
}
size_t test_packet(const uint8_t *p, size_t n, uint8_t out[15]) {
  return secure_dfu_packet(&state, p, n, out);
}
uint32_t test_begins(void) {
  return begins;
}
uint32_t test_writes(void) {
  return writes;
}
uint32_t test_finishes(void) {
  return finishes;
}
bool test_completed(void) {
  return state.completed;
}
const uint8_t *test_flash(void) {
  return flash;
}
void test_fail_write(void) {
  fail_write = true;
}
