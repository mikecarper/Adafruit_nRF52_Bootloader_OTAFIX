#ifndef BOOTLOADER_SETTINGS_GUARD_H_
#define BOOTLOADER_SETTINGS_GUARD_H_

#include <stdbool.h>

#include "bootloader_types.h"

// Existing bootloaders wrote only the original 28-byte prefix.  An erased
// trailer therefore identifies a legacy record, which remains readable after
// basic geometry checks at each use site.
bool bootloader_settings_is_legacy(bootloader_settings_t const* settings);

// New records carry a CRC over the backward-compatible prefix.  The CRC covers
// the intended validity markers, so a geometry-first write is not committed
// until its final marker word reaches flash.
bool bootloader_settings_integrity_valid(bootloader_settings_t const* settings);
void bootloader_settings_seal(bootloader_settings_t* settings);

#endif
