// Shared OTA flash-layout constants for the MeshCore `.mota` delta-apply path on nRF52840.
// SINGLE SOURCE OF TRUTH - keep constants and handoff semantics synchronized with MeshCore
// src/helpers/ota/OtaFlashLayout_nrf52.h.
//
// The running app lives at the SoftDevice end (APP_BASE). Internal ExtraFS, when used, begins at
// 0xD4000; primary InternalFS begins at 0xED000. MeshCore selects the safe staging ceiling for its
// linked layout/storage and passes that choice to the bootloader through GPREGRET2. APP_BASE here is
// the nominal S140 v6 value; the device build uses runtime DFU_BANK_0_REGION_START so it also supports
// S140 v7's one-page-higher application base.

#ifndef OTA_LAYOUT_H_
#define OTA_LAYOUT_H_

#ifndef MOTA_NRF52_APP_BASE
#define MOTA_NRF52_APP_BASE    0x00026000u   // S140 v6 end (host-test default)
#endif
#define MOTA_NRF52_EXTRAFS_START 0x000D4000u // Internal ExtraFS begins here when present
#define MOTA_NRF52_APP_END     0x000ED000u   // Primary InternalFS begins here
#define MOTA_NRF52_STAGE_CEILING_LEGACY   MOTA_NRF52_EXTRAFS_START
#define MOTA_NRF52_STAGE_CEILING_EXPANDED MOTA_NRF52_APP_END
// Compatibility name for the legacy lower boundary. New staging/workspace code uses one of the two
// explicit ceilings above.
#define MOTA_NRF52_FS_START    MOTA_NRF52_EXTRAFS_START
#define MOTA_NRF52_FLASH_PAGE  4096u

// GPREGRET value MeshCore writes (then resets) to ask the bootloader to apply a staged `.mota`.
// Distinct from the Adafruit DFU magics (0x57 UF2, 0x4E serial, 0xA8 OTA-BLE) so it never enters DFU.
#define GPREGRET_OTA_APPLY     0x6Au
// GPREGRET2 tells the bootloader which bottom-aligned staging window the app used. An older app leaves
// a diagnostic/unknown value here; the bootloader deliberately treats every value except EXPANDED as
// LEGACY so it never scans through a possible Internal ExtraFS by accident.
#define GPREGRET2_OTA_STAGE_LEGACY   0xD4u
#define GPREGRET2_OTA_STAGE_EXPANDED 0xEDu

#endif // OTA_LAYOUT_H_
