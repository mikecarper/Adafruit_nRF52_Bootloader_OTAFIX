/* Linker script to configure memory regions. */

SEARCH_DIR(.)
/*GROUP(-lgcc -lc -lnosys)*/

/* The build passes this symbol only for internal-only boards that reserve the
 * fixed mOTA SRAM arena. A zero default keeps every external-storage profile's
 * historical RAM layout unchanged. */
MOTA_RAM_ARENA_SIZE = DEFINED(__mota_ram_arena_size__) ? __mota_ram_arena_size__ : 0;

MEMORY
{
  /** Flash start address for the bootloader. This setting will also be stored in UICR to allow the
   *  MBR to init the bootloader when starting the system. This value must correspond to 
   *  BOOTLOADER_REGION_START found in dfu_types.h. The system is prevented from starting up if 
   *  those values do not match. The check is performed in main.c, see
   *  APP_ERROR_CHECK_BOOL(*((uint32_t *)NRF_UICR_BOOT_START_ADDRESS) == BOOTLOADER_REGION_START);
   */
  /* MeshCore OTA: the in-place delta applier (detools CRLE in-place + sha256 + ota_delta) and fail-closed
     self-update validation do not fit in the stock 38 KB code region. Reclaim 1.75 KB from the CF2
     bootloaderConfig page and give it to FLASH -> 39.75 KB. This is safe for the curated boards:
     bootloaderConfig plus the update manifest is exactly 164 B across the build matrix, is compile-time
     read-only data, and a future board that exceeds the reserved 176 B fails at link time. The
     76-byte BLMF+BLM2 envelope is fixed at the end of the raw bootloader image so candidate validation
     does not need a generic flash scan. Linker assertions prevent the config from colliding with it. The
     bootloader still starts at 0xF4000 (UICR/BOOTLOADER_REGION_START unchanged), and the MBR-params
     (0xFE000) and bootloader-settings (0xFF000) pages remain untouched.

     Full nRF52840 (RAK4631) flash map - only the FLASH/CF2 boundary (*) moves vs stock:

         0x00000  MBR
         0x01000  SoftDevice (S140 6.1.1)
         0x26000  Application  (MeshCore; staged .mota lives just below the filesystem, < 0xD4000)
         ...
         0xF4000  +- bootloader code (FLASH) 39.75 KB -+   stock: 38 KB, ends 0xFD800
         0xFDF50  +- CF2 config + manifest ---- 176 B --+ (*) stock: 2 KB, starts 0xFD800
         0xFDFB4  |  fixed BLMF+BLM2 envelope - 76 B   |
         0xFE000  +- MBR params --------------- 4 KB ---+   unchanged
         0xFF000  +- bootloader settings ------ 4 KB ---+   unchanged
        0x100000  +- (end of flash) --------------------+
  */
     
  FLASH (rx) : ORIGIN = 0xF4000, LENGTH = 0xFE000-0xF4000 - 176

  BOOTLOADER_CONFIG (r): ORIGIN = 0xFE000 - 176, LENGTH = 176

  /** Location of mbr params page in flash. */
  MBR_PARAMS_PAGE (rw) : ORIGIN = 0xFE000, LENGTH = 0x1000
  
  /** Location of bootloader setting in flash. */
  BOOTLOADER_SETTINGS (rw) : ORIGIN = 0xFF000, LENGTH = 0x1000

  /** RAM Region for bootloader. */
  /* Avoid conflict with NOINIT for OTA bond sharing */
  RAM (rwx) :  ORIGIN = 0x20008000, LENGTH = 0x20040000-0x20008000-MOTA_RAM_ARENA_SIZE

  /* Never initialized or used by the bootloader. MeshCore retains a staged
   * container suffix here across the software reset into OTAFIX. */
  MOTA_RAM (rwx) : ORIGIN = 0x20040000-MOTA_RAM_ARENA_SIZE, LENGTH = MOTA_RAM_ARENA_SIZE

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
  } > BOOTLOADER_CONFIG

  .bootloaderManifest ORIGIN(BOOTLOADER_CONFIG) + LENGTH(BOOTLOADER_CONFIG) - 76 :
  {
    KEEP(*(.bootloaderManifest))
  } > BOOTLOADER_CONFIG

  ASSERT(SIZEOF(.bootloaderManifest) == 76,
         "BLMF+BLM2 envelope must be exactly 76 bytes")
  ASSERT(ADDR(.bootloaderConfig) + SIZEOF(.bootloaderConfig) <= ADDR(.bootloaderManifest),
         "bootloaderConfig overlaps fixed BLMF+BLM2 envelope")

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
    __dfu_peer_data_start__ = .;
    KEEP(*(.noinit.peer_data))
    __dfu_peer_data_end__ = .;
    *(.noinit)
    *(.noinit.*)
  } > NOINIT
  ASSERT(__dfu_peer_data_start__ == ORIGIN(NOINIT),
         "retained BLE peer data must start at 0x20007F80")
  ASSERT(__dfu_peer_data_end__ - __dfu_peer_data_start__ == 62,
         "retained BLE peer data ABI must be 60-byte data plus 2-byte CRC")

  .mota_arena (NOLOAD) :
  {
    __mota_ram_start__ = .;
    . += LENGTH(MOTA_RAM);
    __mota_ram_end__ = .;
  } > MOTA_RAM
  ASSERT(MOTA_RAM_ARENA_SIZE == 0 || MOTA_RAM_ARENA_SIZE == 0x10000,
         "mOTA RAM arena must be disabled or exactly 64 KiB")
  ASSERT(__mota_ram_start__ == 0x20040000 - MOTA_RAM_ARENA_SIZE,
         "mOTA RAM arena start does not match the retained ABI")
  ASSERT(__mota_ram_end__ == 0x20040000,
         "mOTA RAM arena must end at physical SRAM top")
  ASSERT(SIZEOF(.mota_arena) == MOTA_RAM_ARENA_SIZE,
         "mOTA RAM arena section has the wrong size")
  /* other placements follow here... */
}

INCLUDE "nrf_common.ld"

ASSERT(__StackTop == __mota_ram_start__,
       "bootloader stack must end immediately below the mOTA RAM arena")
ASSERT(__StackLimit >= __HeapLimit,
       "bootloader stack/data overlap after reserving the mOTA RAM arena")
