#include "ota_qspi_alignment.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define TEST_CAPACITY    32u
#define TEST_BOUNCE_SIZE 8u

static uint8_t flash_data[TEST_CAPACITY];

static void assert_window(uint32_t offset, uint32_t requested, uint32_t expected_offset,
                          uint32_t expected_length, uint32_t expected_prefix,
                          uint32_t expected_copy) {
  ota_qspi_dma_window_t window;
  assert(ota_qspi_dma_window(offset, requested, TEST_CAPACITY, TEST_BOUNCE_SIZE, &window));
  assert(window.offset == expected_offset);
  assert(window.length == expected_length);
  assert(window.prefix == expected_prefix);
  assert(window.copy_length == expected_copy);
}

static bool simulated_read(uint32_t offset, uint8_t *dst, uint32_t len) {
  uint8_t bounce[TEST_BOUNCE_SIZE] __attribute__((aligned(4)));

  if (dst == NULL || (uint64_t)offset + len > TEST_CAPACITY) {
    return false;
  }
  while (len != 0) {
    ota_qspi_dma_window_t window;
    if (!ota_qspi_dma_window(offset, len, TEST_CAPACITY, sizeof(bounce), &window)) {
      return false;
    }
    assert((window.offset & 3u) == 0);
    assert((window.length & 3u) == 0);
    memcpy(bounce, flash_data + window.offset, window.length);
    memcpy(dst, bounce + window.prefix, window.copy_length);
    offset += window.copy_length;
    dst += window.copy_length;
    len -= window.copy_length;
  }
  return true;
}

static void test_read_windows(void) {
  assert_window(1, 1, 0, 4, 1, 1);
  assert_window(1, 3, 0, 4, 1, 3);
  assert_window(1, 5, 0, 8, 1, 5);
  assert_window(3, 8, 0, 8, 3, 5);
  assert_window(29, 3, 28, 4, 1, 3);
  assert_window(31, 1, 28, 4, 3, 1);

  ota_qspi_dma_window_t window;
  assert(!ota_qspi_dma_window(30, 3, TEST_CAPACITY, TEST_BOUNCE_SIZE, &window));
  assert(!ota_qspi_dma_window(0, 1, TEST_CAPACITY, 7, &window));
  assert(!ota_qspi_dma_window(0, 0, TEST_CAPACITY, TEST_BOUNCE_SIZE, &window));
  // Range checks must reject wrapped addition as well as ordinary overrun.
  assert(!ota_qspi_dma_window(UINT32_MAX, 2, TEST_CAPACITY, TEST_BOUNCE_SIZE, &window));
  assert(!ota_qspi_dma_window(4, UINT32_MAX, TEST_CAPACITY, TEST_BOUNCE_SIZE, &window));
  assert(!ota_qspi_dma_window(UINT32_MAX - 3u, 4, UINT32_MAX - 3u, 256, &window));
  assert(ota_qspi_dma_window(UINT32_MAX - 7u, 4, UINT32_MAX - 3u, 256, &window));
  assert(window.offset == UINT32_MAX - 7u && window.length == 4u);
}

static void test_unaligned_reads(void) {
  for (uint32_t i = 0; i < TEST_CAPACITY; i++) {
    flash_data[i] = (uint8_t)(0x40u + i);
  }

  uint8_t output[24];
  memset(output, 0, sizeof(output));
  assert(simulated_read(1, output + 1, 1));
  assert(output[1] == flash_data[1]);

  memset(output, 0, sizeof(output));
  assert(simulated_read(1, output + 1, 3));
  assert(memcmp(output + 1, flash_data + 1, 3) == 0);

  memset(output, 0, sizeof(output));
  assert(simulated_read(1, output + 1, 5));
  assert(memcmp(output + 1, flash_data + 1, 5) == 0);

  memset(output, 0, sizeof(output));
  assert(simulated_read(3, output + 1, 19));
  assert(memcmp(output + 1, flash_data + 3, 19) == 0);

  assert(simulated_read(29, output + 1, 3));
  assert(memcmp(output + 1, flash_data + 29, 3) == 0);
  assert(!simulated_read(30, output, 3));
}

static void test_unaligned_nor_overlay(void) {
  ota_qspi_dma_window_t window;
  assert(ota_qspi_dma_window(201, 4, 256, 256, &window));
  assert(window.offset == 200);
  assert(window.length == 8);
  assert(window.prefix == 1);
  assert(window.copy_length == 4);

  uint8_t data[8] = {0xA5, 0xFF, 0x7F, 0x55, 0x01, 0xC3, 0x3C, 0x5A};
  uint8_t expected_neighbors[8];
  memcpy(expected_neighbors, data, sizeof(data));
  const uint8_t clear_approval[4] = {0, 0, 0, 0};
  assert(ota_qspi_nor_overlay(data, sizeof(data), window.prefix, clear_approval,
                              sizeof(clear_approval)));
  assert(memcmp(data + window.prefix, clear_approval, sizeof(clear_approval)) == 0);
  assert(data[0] == expected_neighbors[0]);
  assert(memcmp(data + 5, expected_neighbors + 5, 3) == 0);

  uint8_t programmed[8] = {0xAA, 0x00, 0x55, 0xAA, 0x55, 0xCC, 0x33, 0xF0};
  uint8_t unchanged[8];
  memcpy(unchanged, programmed, sizeof(programmed));
  const uint8_t illegal_set[1] = {0x01};
  assert(!ota_qspi_nor_overlay(programmed, sizeof(programmed), 1, illegal_set,
                               sizeof(illegal_set)));
  assert(memcmp(programmed, unchanged, sizeof(programmed)) == 0);
}

int main(void) {
  test_read_windows();
  test_unaligned_reads();
  test_unaligned_nor_overlay();
  puts("QSPI EasyDMA alignment: PASS");
  return 0;
}
