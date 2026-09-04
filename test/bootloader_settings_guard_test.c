#include "bootloader_settings_guard.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

uint16_t crc16_compute(uint8_t const* data, uint32_t size,
                       uint16_t const* previous) {
  uint16_t crc = previous == NULL ? UINT16_MAX : *previous;
  for (uint32_t i = 0; i < size; i++) {
    crc = (uint8_t)(crc >> 8) | (uint16_t)(crc << 8);
    crc ^= data[i];
    crc ^= (uint8_t)(crc & 0xFFu) >> 4;
    crc ^= (uint16_t)((crc << 8) << 4);
    crc ^= (uint16_t)(((crc & 0xFFu) << 4) << 1);
  }
  return crc;
}

static bootloader_settings_t valid_settings(void) {
  bootloader_settings_t settings;
  memset(&settings, 0, sizeof(settings));
  settings.bank_0 = BANK_VALID_APP;
  settings.bank_0_crc = 0x1234u;
  settings.bank_1 = BANK_INVALID_APP;
  settings.bank_0_size = 0x45678u;
  bootloader_settings_seal(&settings);
  return settings;
}

int main(void) {
  bootloader_settings_t settings = valid_settings();
  assert(!bootloader_settings_is_legacy(&settings));
  assert(bootloader_settings_integrity_valid(&settings));
  assert(settings.record_crc_inv == (uint16_t)~settings.record_crc);

  for (size_t offset = 0; offset < offsetof(bootloader_settings_t, record_crc);
       offset++) {
    bootloader_settings_t corrupt = settings;
    ((uint8_t*)&corrupt)[offset] ^= 1u;
    assert(!bootloader_settings_integrity_valid(&corrupt));
  }

  bootloader_settings_t legacy = settings;
  legacy.format_version = 0u;
  legacy.record_crc = UINT16_MAX;
  legacy.record_crc_inv = UINT16_MAX;
  assert(bootloader_settings_is_legacy(&legacy));
  assert(bootloader_settings_integrity_valid(&legacy));

  // Mirror the device write order: geometry/trailer, secondary marker, then
  // the first marker word as the transaction commit point.
  bootloader_settings_t flash;
  memset(&flash, 0xFF, sizeof(flash));
  memcpy((uint8_t*)&flash + 2u * sizeof(uint32_t),
         (uint8_t const*)&settings + 2u * sizeof(uint32_t),
         sizeof(settings) - 2u * sizeof(uint32_t));
  assert(!bootloader_settings_integrity_valid(&flash));
  memcpy((uint8_t*)&flash + sizeof(uint32_t),
         (uint8_t const*)&settings + sizeof(uint32_t), sizeof(uint32_t));
  assert(!bootloader_settings_integrity_valid(&flash));
  memcpy(&flash, &settings, sizeof(uint32_t));
  assert(bootloader_settings_integrity_valid(&flash));
  assert(memcmp(&flash, &settings, sizeof(settings)) == 0);

  puts("bootloader settings integrity and commit ordering: PASS");
  return 0;
}
