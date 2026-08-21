/* Linker script to configure memory regions. */

SEARCH_DIR(.)
/*GROUP(-lgcc -lc -lnosys)*/

MEMORY
{
  /** Flash start address for the bootloader. This setting will also be stored in UICR to allow the
   *  MBR to init the bootloader when starting the system. This value must correspond to 
   *  BOOTLOADER_REGION_START found in dfu_types.h. The system is prevented from starting up if 
   *  those values do not match. The check is performed in main.c, see
   *  APP_ERROR_CHECK_BOOL(*((uint32_t *)NRF_UICR_BOOT_START_ADDRESS) == BOOTLOADER_REGION_START);
   */
  /* MeshCore OTA: the in-place delta applier (detools CRLE in-place + sha256 + ota_delta) and fail-closed
     UF2 self-update validation do not fit in the stock 38 KB code region. Reclaim 1.5 KB from the CF2
     bootloaderConfig page and give it to FLASH -> 39.5 KB. This is safe for the curated boards:
     bootloaderConfig plus the update manifest is currently 132 B, is compile-time read-only data, and a
     future board that exceeds the reserved 512 B fails at link time rather than at runtime. The
     bootloader still starts at 0xF4000 (UICR/BOOTLOADER_REGION_START unchanged), and the MBR-params
     (0xFE000) and bootloader-settings (0xFF000) pages remain untouched.

     Full nRF52840 (RAK4631) flash map - only the FLASH/CF2 boundary (*) moves vs stock:

         0x00000  MBR
         0x01000  SoftDevice (S140 6.1.1)
         0x26000  Application  (MeshCore; staged .mota lives just below the filesystem, < 0xD4000)
         ...
         0xF4000  +- bootloader code (FLASH) - 39.5 KB -+   stock: 38 KB, ends 0xFD800
         0xFDE00  +- CF2 config + manifest ---- 512 B --+ (*) stock: 2 KB, starts 0xFD800
         0xFE000  +- MBR params --------------- 4 KB ---+   unchanged
         0xFF000  +- bootloader settings ------ 4 KB ---+   unchanged
        0x100000  +- (end of flash) --------------------+
  */
     
  FLASH (rx) : ORIGIN = 0xF4000, LENGTH = 0xFE000-0xF4000 - 512 /* 39.5 KB */

  BOOTLOADER_CONFIG (r): ORIGIN = 0xFE000 - 512, LENGTH = 512

  /** Location of mbr params page in flash. */
  MBR_PARAMS_PAGE (rw) : ORIGIN = 0xFE000, LENGTH = 0x1000
  
  /** Location of bootloader setting in flash. */
  BOOTLOADER_SETTINGS (rw) : ORIGIN = 0xFF000, LENGTH = 0x1000

  /** RAM Region for bootloader. */
  /* Avoid conflict with NOINIT for OTA bond sharing */
  RAM (rwx) :  ORIGIN = 0x20008000, LENGTH = 0x20040000-0x20008000

  /* Location for double reset detection, no init */
  DBL_RESET (rwx) :  ORIGIN = 0x20007F7C, LENGTH = 0x04
  
  /** Location of non initialized RAM. Non initialized RAM is used for exchanging bond information
   *  from application to bootloader when using buttonless DFU OTA. */
  NOINIT (rwx) :  ORIGIN = 0x20007F80, LENGTH = 0x80

  /** Location in UICR where bootloader start address is stored. */
  UICR_BOOTLOADER (r) : ORIGIN = 0x10001014, LENGTH = 0x04
  
  /** Location in UICR where mbr params page address is stored. */
  UICR_MBR_PARAM_PAGE(r) : ORIGIN = 0x10001018, LENGTH = 0x04
}

SECTIONS
{
  .fs_data_out ALIGN(4):
  {
    PROVIDE( __start_fs_data = .);
    KEEP(*(fs_data))
    PROVIDE( __stop_fs_data = .);
  } = 0

  .bootloaderConfig :
  {
    KEEP(*(.bootloaderConfig))
    KEEP(*(.bootloaderManifest))
  } > BOOTLOADER_CONFIG

  /* Place the bootloader settings page in flash. */
  .bootloaderSettings(NOLOAD) :
  {
    
  } > BOOTLOADER_SETTINGS

  /* Write the bootloader address in UICR. */
  .uicrBootStartAddress : 
  {
    KEEP(*(.uicrBootStartAddress))
  } > UICR_BOOTLOADER
  
  /* Place the mbr params page in flash. */
    .mbrParamsPage(NOLOAD) :
  {
    
  } > MBR_PARAMS_PAGE
  
  /* Write the bootloader address in UICR. */
  .uicrMbrParamsPageAddress :
  {
    KEEP(*(.uicrMbrParamsPageAddress))
  } > UICR_MBR_PARAM_PAGE

  .dbl_reset(NOLOAD) :
  {

  } > DBL_RESET

  /* No init RAM section in bootloader. Used for bond information exchange. */
  .noinit(NOLOAD) :
  {

  } > NOINIT
  /* other placements follow here... */
}

INCLUDE "nrf_common.ld"
