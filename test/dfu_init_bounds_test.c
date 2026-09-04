#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "crc16.h"
#include "dfu_init.h"
#include "dfu_types.h"
#include "nrf_error.h"

uint16_t crc16_compute(uint8_t const *data, uint32_t size, uint16_t const *previous) {
  (void)data;
  (void)size;
  (void)previous;
  return 0;
}

#ifdef SIGNED_FW
#include <tinycrypt/constants.h>
#include <tinycrypt/ecc.h>
#include <tinycrypt/ecc_dsa.h>
#include <tinycrypt/sha256.h>

int tc_sha256_init(TCSha256State_t state) {
  (void)state;
  return TC_CRYPTO_SUCCESS;
}

int tc_sha256_update(TCSha256State_t state, const uint8_t *data, size_t data_len) {
  (void)state;
  (void)data;
  (void)data_len;
  return TC_CRYPTO_SUCCESS;
}

int tc_sha256_final(uint8_t *digest, TCSha256State_t state) {
  (void)state;
  memset(digest, 0, TC_SHA256_DIGEST_SIZE);
  return TC_CRYPTO_SUCCESS;
}

uECC_Curve uECC_secp256r1(void) {
  return (uECC_Curve)(uintptr_t)1;
}

int uECC_valid_public_key(const uint8_t *public_key, uECC_Curve curve) {
  (void)public_key;
  (void)curve;
  return 0;
}

int uECC_verify(const uint8_t *public_key, const uint8_t *message_hash,
                unsigned int hash_size, const uint8_t *signature, uECC_Curve curve) {
  (void)public_key;
  (void)message_hash;
  (void)hash_size;
  (void)signature;
  (void)curve;
  return 1;
}
#endif

static void put_u16(uint8_t *dst, uint16_t value) {
  dst[0] = (uint8_t)value;
  dst[1] = (uint8_t)(value >> 8);
}

static void put_u32(uint8_t *dst, uint32_t value) {
  dst[0] = (uint8_t)value;
  dst[1] = (uint8_t)(value >> 8);
  dst[2] = (uint8_t)(value >> 16);
  dst[3] = (uint8_t)(value >> 24);
}

static uint32_t make_valid_packet(uint8_t packet[128], uint32_t padding) {
  memset(packet, 0, 128);
  put_u16(packet, 0x0052u);
  put_u16(packet + 2, 52840u);
  put_u32(packet + 4, 1u);
  put_u16(packet + 8, 1u);
  put_u16(packet + 10, DFU_SOFTDEVICE_ANY);

#ifdef SIGNED_FW
  enum { EXTENDED_LENGTH = 104 };
  put_u32(packet + 12, 2u);
#else
  enum { EXTENDED_LENGTH = 2 };
#endif
  return 12u + EXTENDED_LENGTH + padding;
}

int main(void) {
  uint8_t packet[128] __attribute__((aligned(4)));
  uint8_t unaligned_storage[129] __attribute__((aligned(4)));

  assert(dfu_init_prevalidate(NULL, 0, DFU_UPDATE_APP) == NRF_ERROR_NULL);

  uint32_t length = make_valid_packet(packet, 0);
  assert(dfu_init_prevalidate(packet, length, DFU_UPDATE_APP) == NRF_SUCCESS);

  length = make_valid_packet(unaligned_storage + 1, 0);
  assert(dfu_init_prevalidate(unaligned_storage + 1, length, DFU_UPDATE_APP) == NRF_SUCCESS);

  length = make_valid_packet(packet, 3);
  assert(dfu_init_prevalidate(packet, length, DFU_UPDATE_APP) == NRF_SUCCESS);
  packet[length - 1] = 1;
  assert(dfu_init_prevalidate(packet, length, DFU_UPDATE_APP) == NRF_SUCCESS);

  length = make_valid_packet(packet, 4);
  assert(dfu_init_prevalidate(packet, length, DFU_UPDATE_APP) == NRF_ERROR_INVALID_LENGTH);

  // This maximum-size packet overflowed the 104-byte destination before the
  // parser checked the declared SoftDevice list or extension geometry.
  memset(packet, 0xA5, sizeof(packet));
  put_u16(packet, 0x0052u);
  put_u16(packet + 2, 52840u);
  put_u16(packet + 8, 0u);
  assert(dfu_init_prevalidate(packet, sizeof(packet), DFU_UPDATE_APP) == NRF_ERROR_INVALID_LENGTH);

  memset(packet, 0, sizeof(packet));
  put_u16(packet, 0x0052u);
  put_u16(packet + 2, 52840u);
  put_u16(packet + 8, UINT16_MAX);
  assert(dfu_init_prevalidate(packet, 12, DFU_UPDATE_APP) == NRF_ERROR_INVALID_LENGTH);

#ifdef SIGNED_FW
  puts("signed Legacy DFU init bounds: PASS");
#else
  puts("unsigned Legacy DFU init bounds: PASS");
#endif
  return 0;
}
