#include "bootloader_settings_guard.h"

#include <stddef.h>
#include <stdint.h>

#include "crc16.h"

bool bootloader_settings_is_legacy(bootloader_settings_t const* settings) {
  return settings != NULL && settings->record_crc == UINT16_MAX &&
         settings->record_crc_inv == UINT16_MAX;
}

bool bootloader_settings_integrity_valid(bootloader_settings_t const* settings) {
  if (settings == NULL) {
    return false;
  }
  if (bootloader_settings_is_legacy(settings)) {
    return true;
  }
  if (settings->format_version != BOOTLOADER_SETTINGS_FORMAT_VERSION ||
      settings->record_crc_inv != (uint16_t)~settings->record_crc) {
    return false;
  }
  return crc16_compute((uint8_t const*)settings,
                       offsetof(bootloader_settings_t, record_crc), NULL) ==
         settings->record_crc;
}

void bootloader_settings_seal(bootloader_settings_t* settings) {
  settings->format_version = BOOTLOADER_SETTINGS_FORMAT_VERSION;
  settings->record_crc = crc16_compute(
      (uint8_t const*)settings, offsetof(bootloader_settings_t, record_crc), NULL);
  settings->record_crc_inv = (uint16_t)~settings->record_crc;
}
