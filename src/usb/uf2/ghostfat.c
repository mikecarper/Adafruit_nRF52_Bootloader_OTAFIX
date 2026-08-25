/*
 * The MIT License (MIT)
 *
 * Copyright (c) Microsoft Corporation
 * Copyright (c) 2020 Ha Thach for Adafruit Industries
 * Copyright (c) 2020 Henry Gabryjelski
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 */

#include "compile_date.h"

#include "uf2.h"
#include "uf2_app_flash.h"
#include "uf2_transfer_state.h"
#include "bootloader_image.h"
#if defined(MOTA_INTERNAL_BOOTLOADER_UPDATE) || defined(MOTA_SD_BOOTLOADER_UPDATE)
  #include "ota_delta.h"
  #include "ota_layout.h"
#endif
#include "configkeys.h"
#include "flash_nrf5x.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

#include "bootloader_settings.h"
#include "bootloader.h"

//--------------------------------------------------------------------+
//
//--------------------------------------------------------------------+

// Add nonstring attribute if supported to avoid errors in GCC 15
#if defined(__has_attribute) && __has_attribute(nonstring)
  #define ATTR_NONSTRING __attribute__((nonstring))
#else
  #define ATTR_NONSTRING
#endif

typedef struct {
    uint8_t JumpInstruction[3];
  uint8_t  OEMInfo[8] ATTR_NONSTRING;
  uint16_t SectorSize;
  uint8_t  SectorsPerCluster;
  uint16_t ReservedSectors;
    uint8_t FATCopies;
    uint16_t RootDirectoryEntries;
    uint16_t TotalSectors16;
    uint8_t MediaDescriptor;
    uint16_t SectorsPerFAT;
    uint16_t SectorsPerTrack;
    uint16_t Heads;
    uint32_t HiddenSectors;
    uint32_t TotalSectors32;
    uint8_t PhysicalDriveNum;
    uint8_t Reserved;
    uint8_t ExtendedBootSig;
    uint32_t VolumeSerialNumber;
    uint8_t  VolumeLabel[11] ATTR_NONSTRING;
    uint8_t  FilesystemIdentifier[8] ATTR_NONSTRING;
} __attribute__((packed)) FAT_BootBlock;

typedef struct {
    char name[8];
    char ext[3];
    uint8_t attrs;
    uint8_t reserved;
    uint8_t createTimeFine;
    uint16_t createTime;
    uint16_t createDate;
    uint16_t lastAccessDate;
    uint16_t highStartCluster;
    uint16_t updateTime;
    uint16_t updateDate;
    uint16_t startCluster;
    uint32_t size;
} __attribute__((packed)) DirEntry;
STATIC_ASSERT(sizeof(DirEntry) == 32);

struct TextFile {
  const char  name[11] ATTR_NONSTRING;
  const char *content;
};


//--------------------------------------------------------------------+
//
//--------------------------------------------------------------------+

#define BPB_SECTOR_SIZE           ( 512)
#define BPB_SECTORS_PER_CLUSTER   (   1)
#define BPB_RESERVED_SECTORS      (   1)
#define BPB_NUMBER_OF_FATS        (   2)
#define BPB_ROOT_DIR_ENTRIES      (  64)
#define BPB_TOTAL_SECTORS         CFG_UF2_NUM_BLOCKS
#define BPB_MEDIA_DESCRIPTOR_BYTE (0xF8)
#define FAT_ENTRY_SIZE            (2)
#define FAT_ENTRIES_PER_SECTOR    (BPB_SECTOR_SIZE / FAT_ENTRY_SIZE)
// NOTE: MS specification explicitly allows FAT to be larger than necessary
#define BPB_SECTORS_PER_FAT       ( (BPB_TOTAL_SECTORS / FAT_ENTRIES_PER_SECTOR) + \
                                   ((BPB_TOTAL_SECTORS % FAT_ENTRIES_PER_SECTOR) ? 1 : 0))
#define DIRENTRIES_PER_SECTOR     (BPB_SECTOR_SIZE/sizeof(DirEntry))
#define ROOT_DIR_SECTOR_COUNT     (BPB_ROOT_DIR_ENTRIES/DIRENTRIES_PER_SECTOR)

STATIC_ASSERT(BPB_SECTOR_SIZE                              ==       512); // GhostFAT does not support other sector sizes (currently)
STATIC_ASSERT(BPB_SECTORS_PER_CLUSTER                      ==         1); // GhostFAT presumes one sector == one cluster (for simplicity)
STATIC_ASSERT(BPB_NUMBER_OF_FATS                           ==         2); // FAT highest compatibility
STATIC_ASSERT(sizeof(DirEntry)                             ==        32); // FAT requirement
STATIC_ASSERT(BPB_SECTOR_SIZE % sizeof(DirEntry)           ==         0); // FAT requirement
STATIC_ASSERT(BPB_ROOT_DIR_ENTRIES % DIRENTRIES_PER_SECTOR ==         0); // FAT requirement
STATIC_ASSERT(BPB_SECTOR_SIZE * BPB_SECTORS_PER_CLUSTER    <= (32*1024)); // FAT requirement (64k+ has known compatibility problems)
STATIC_ASSERT(FAT_ENTRIES_PER_SECTOR                       ==       256); // FAT requirement

#define STR0(x) #x
#define STR(x) STR0(x)

#if defined(MOTA_INTERNAL_BOOTLOADER_UPDATE) || defined(MOTA_QSPI_BOOTLOADER_UPDATE) || \
    defined(MOTA_SD_BOOTLOADER_UPDATE)
  // Self-update builds use the build-bound SoftDevice label already exposed by
  // BLE DIS. This avoids carrying a runtime decimal formatter and oversized
  // mutable suffix buffer in the flash-constrained, fail-closed bootloader.
  #define INFO_UF2_INITIAL_CONTENT \
    "UF2 Bootloader " BLEDIS_FW_VERSION "\r\n" \
    "Model: " UF2_PRODUCT_NAME "\r\n" \
    "Board-ID: " UF2_BOARD_ID "\r\n" \
    "Date: " __DATE__ "\r\n"
const char infoUf2File[] = INFO_UF2_INITIAL_CONTENT;
#else
  #define INFO_UF2_INITIAL_CONTENT \
    "UF2 Bootloader " UF2_VERSION "\r\n" \
    "Model: " UF2_PRODUCT_NAME "\r\n" \
    "Board-ID: " UF2_BOARD_ID "\r\n" \
    "Date: " __DATE__ "\r\n"

  // Keep enough room for the runtime "SoftDevice: S<id> x.y.z" suffix.
  char infoUf2File[sizeof(INFO_UF2_INITIAL_CONTENT) + 48] = INFO_UF2_INITIAL_CONTENT;
#endif

const char indexFile[] =
    "<!doctype html>\n"
    "<html>"
    "<body>"
    "<script>\n"
    "location.replace(\"" UF2_INDEX_URL "\");\n"
    "</script>"
    "</body>"
    "</html>\n";

static struct TextFile const info[] = {
    {.name = "INFO_UF2TXT", .content = infoUf2File},
    {.name = "INDEX   HTM", .content = indexFile},

    // current.uf2 must be the last element and its content must be NULL
    {.name = "CURRENT UF2", .content = NULL},
};
STATIC_ASSERT(ARRAY_SIZE(infoUf2File) < BPB_SECTOR_SIZE); // GhostFAT requires files to fit in one sector
STATIC_ASSERT(ARRAY_SIZE(indexFile)   < BPB_SECTOR_SIZE); // GhostFAT requires files to fit in one sector

#define NUM_FILES          (ARRAY_SIZE(info))
#define NUM_DIRENTRIES     (NUM_FILES + 1) // Code adds volume label as first root directory entry
#define REQUIRED_ROOT_DIRECTORY_SECTORS ( ((NUM_DIRENTRIES+1) / DIRENTRIES_PER_SECTOR) + \
                                         (((NUM_DIRENTRIES+1) % DIRENTRIES_PER_SECTOR) ? 1 : 0))
STATIC_ASSERT(ROOT_DIR_SECTOR_COUNT >= REQUIRED_ROOT_DIRECTORY_SECTORS);         // FAT requirement -- Ensures BPB reserves sufficient entries for all files
STATIC_ASSERT(NUM_DIRENTRIES < (DIRENTRIES_PER_SECTOR * ROOT_DIR_SECTOR_COUNT)); // FAT requirement -- end directory with unused entry
STATIC_ASSERT(NUM_DIRENTRIES < BPB_ROOT_DIR_ENTRIES);                            // FAT requirement -- Ensures BPB reserves sufficient entries for all files
STATIC_ASSERT(NUM_DIRENTRIES < DIRENTRIES_PER_SECTOR); // GhostFAT bug workaround -- else, code overflows buffer

#define NUM_SECTORS_IN_DATA_REGION (BPB_TOTAL_SECTORS - BPB_RESERVED_SECTORS - (BPB_NUMBER_OF_FATS * BPB_SECTORS_PER_FAT) - ROOT_DIR_SECTOR_COUNT)
#define CLUSTER_COUNT              (NUM_SECTORS_IN_DATA_REGION / BPB_SECTORS_PER_CLUSTER)

// Ensure cluster count results in a valid FAT16 volume!
STATIC_ASSERT( CLUSTER_COUNT >= 0x0FF5 && CLUSTER_COUNT < 0xFFF5 );

// Many existing FAT implementations have small (1-16) off-by-one style errors
// So, avoid being within 32 of those limits for even greater compatibility.
STATIC_ASSERT( CLUSTER_COUNT >= 0x1015 && CLUSTER_COUNT < 0xFFD5 );


#define UF2_FIRMWARE_BYTES_PER_SECTOR 256
#define TRUE_USER_FLASH_SIZE (USER_FLASH_END-USER_FLASH_START)
STATIC_ASSERT(TRUE_USER_FLASH_SIZE % UF2_FIRMWARE_BYTES_PER_SECTOR == 0); // UF2 requirement -- overall size must be integral multiple of per-sector payload?

#define UF2_SECTORS        ( (TRUE_USER_FLASH_SIZE / UF2_FIRMWARE_BYTES_PER_SECTOR) + \
                            ((TRUE_USER_FLASH_SIZE % UF2_FIRMWARE_BYTES_PER_SECTOR) ? 1 : 0))
#define UF2_SIZE           (UF2_SECTORS * BPB_SECTOR_SIZE)

STATIC_ASSERT(UF2_SECTORS == ((UF2_SIZE/2) / 256)); // Not a requirement ... ensuring replacement of literal value is not a change

#define UF2_FIRST_SECTOR   ((NUM_FILES + 1) * BPB_SECTORS_PER_CLUSTER) // WARNING -- code presumes each non-UF2 file content fits in single sector
#define UF2_LAST_SECTOR    ((UF2_FIRST_SECTOR + UF2_SECTORS - 1) * BPB_SECTORS_PER_CLUSTER)

#define FS_START_FAT0_SECTOR      BPB_RESERVED_SECTORS
#define FS_START_FAT1_SECTOR      (FS_START_FAT0_SECTOR + BPB_SECTORS_PER_FAT)
#define FS_START_ROOTDIR_SECTOR   (FS_START_FAT1_SECTOR + BPB_SECTORS_PER_FAT)
#define FS_START_CLUSTERS_SECTOR  (FS_START_ROOTDIR_SECTOR + ROOT_DIR_SECTOR_COUNT)


static FAT_BootBlock const BootBlock = {
    .JumpInstruction      = {0xeb, 0x3c, 0x90},
    .OEMInfo              = "UF2 UF2 ",
    .SectorSize           = BPB_SECTOR_SIZE,
    .SectorsPerCluster    = BPB_SECTORS_PER_CLUSTER,
    .ReservedSectors      = BPB_RESERVED_SECTORS,
    .FATCopies            = BPB_NUMBER_OF_FATS,
    .RootDirectoryEntries = BPB_ROOT_DIR_ENTRIES,
    .TotalSectors16       = (BPB_TOTAL_SECTORS > 0xFFFF) ? 0 : BPB_TOTAL_SECTORS,
    .MediaDescriptor      = BPB_MEDIA_DESCRIPTOR_BYTE,
    .SectorsPerFAT        = BPB_SECTORS_PER_FAT,
    .SectorsPerTrack      = 1,
    .Heads                = 1,
    .TotalSectors32       = (BPB_TOTAL_SECTORS > 0xFFFF) ? BPB_TOTAL_SECTORS : 0,
    .PhysicalDriveNum     = 0x80, // to match MediaDescriptor of 0xF8
    .ExtendedBootSig      = 0x29,
    .VolumeSerialNumber   = 0x00420042,
    .VolumeLabel          = UF2_VOLUME_LABEL,
    .FilesystemIdentifier = "FAT16   ",
};

//--------------------------------------------------------------------+
//
//--------------------------------------------------------------------+
static inline bool is_uf2_block (UF2_Block const *bl)
{
  return (bl->magicStart0 == UF2_MAGIC_START0) &&
         (bl->magicStart1 == UF2_MAGIC_START1) &&
         (bl->magicEnd == UF2_MAGIC_END) &&
         (bl->flags & UF2_FLAG_FAMILYID) &&
         !(bl->flags & UF2_FLAG_NOFLASH) &&
         (bl->payloadSize == UF2_FIRMWARE_BYTES_PER_SECTOR) &&
         !(bl->targetAddr & 0xff);
}

// used when upgrading application
static inline bool in_app_space (uint32_t addr)
{
  return USER_FLASH_START <= addr && addr < USER_FLASH_END;
}

// used when upgrading bootloader
static inline bool in_bootloader_space (uint32_t addr)
{
  return BOOTLOADER_ADDR_START <= addr && addr < BOOTLOADER_ADDR_END;
}

// used when upgrading bootloader
static inline bool in_uicr_space(uint32_t addr)
{
  return addr == 0x10001000;
}

//--------------------------------------------------------------------+
//
//--------------------------------------------------------------------+

void uf2_init(void)
{
#if !defined(MOTA_INTERNAL_BOOTLOADER_UPDATE) && !defined(MOTA_QSPI_BOOTLOADER_UPDATE) && \
    !defined(MOTA_SD_BOOTLOADER_UPDATE)
  strcat(infoUf2File, "SoftDevice: ");

  if ( is_sd_existed() )
  {
    uint32_t const sd_id      = SD_ID_GET(MBR_SIZE);
    uint32_t const sd_version = SD_VERSION_GET(MBR_SIZE);

    uint32_t ver[3];
    ver[0] = sd_version / 1000000;
    ver[1] = (sd_version - ver[0]*1000000)/1000;
    ver[2] = (sd_version - ver[0]*1000000 - ver[1]*1000);

    char str[10];
    utoa(sd_id, str, 10);

    strcat(infoUf2File, "S");
    strcat(infoUf2File, str);
    strcat(infoUf2File, " ");

    utoa(ver[0], str, 10);
    strcat(infoUf2File, str);
    strcat(infoUf2File, ".");

    utoa(ver[1], str, 10);
    strcat(infoUf2File, str);
    strcat(infoUf2File, ".");

    utoa(ver[2], str, 10);
    strcat(infoUf2File, str);
    strcat(infoUf2File, "\r\n");
  }else
  {
    strcat(infoUf2File, "not found\r\n");
  }
#endif
}

/*------------------------------------------------------------------*/
/* Read CURRENT.UF2
 *------------------------------------------------------------------*/
void padded_memcpy (char *dst, char const *src, int len)
{
  for ( int i = 0; i < len; ++i )
  {
    if ( *src ) {
      *dst = *src++;
    } else {
      *dst = ' ';
    }
    dst++;
  }
}

void read_block(uint32_t block_no, uint8_t *data) {
    memset(data, 0, BPB_SECTOR_SIZE);
    uint32_t sectionIdx = block_no;

    if (block_no == 0) { // Requested boot block
        memcpy(data, &BootBlock, sizeof(BootBlock));
        data[510] = 0x55; // Always at offsets 510/511, even when BPB_SECTOR_SIZE is larger
        data[511] = 0xaa; // Always at offsets 510/511, even when BPB_SECTOR_SIZE is larger
        // logval("data[0]", data[0]);
    } else if (block_no < FS_START_ROOTDIR_SECTOR) {  // Requested FAT table sector
        sectionIdx -= FS_START_FAT0_SECTOR;
        // logval("sidx", sectionIdx);
        if (sectionIdx >= BPB_SECTORS_PER_FAT) {
            sectionIdx -= BPB_SECTORS_PER_FAT; // second FAT is same as the first...
        }
        if (sectionIdx == 0) {
            // first FAT entry must match BPB MediaDescriptor
            data[0] = BPB_MEDIA_DESCRIPTOR_BYTE;
            // WARNING -- code presumes only one NULL .content for .UF2 file
            //            and all non-NULL .content fit in one sector
            //            and requires it be the last element of the array
            uint32_t const end = (NUM_FILES * FAT_ENTRY_SIZE) + (2 * FAT_ENTRY_SIZE);
            for (uint32_t i = 1; i < end; ++i) {
                data[i] = 0xff;
            }
        }
        for (uint32_t i = 0; i < FAT_ENTRIES_PER_SECTOR; ++i) { // Generate the FAT chain for the firmware "file"
            uint32_t v = (sectionIdx * FAT_ENTRIES_PER_SECTOR) + i;
            if (UF2_FIRST_SECTOR <= v && v <= UF2_LAST_SECTOR)
                ((uint16_t *)(void *)data)[i] = v == UF2_LAST_SECTOR ? 0xffff : v + 1;
        }
    } else if (block_no < FS_START_CLUSTERS_SECTOR) { // Requested root directory sector

        sectionIdx -= FS_START_ROOTDIR_SECTOR;

        DirEntry *d = (void *)data;
        int remainingEntries = DIRENTRIES_PER_SECTOR;
        if (sectionIdx == 0) { // volume label first
            // volume label is first directory entry
            padded_memcpy(d->name, (char const *) BootBlock.VolumeLabel, 11);
            d->attrs = 0x28;
            d++;
            remainingEntries--;
        }

        for (uint32_t i = DIRENTRIES_PER_SECTOR * sectionIdx;
             remainingEntries > 0 && i < NUM_FILES;
             i++, d++) {

            // WARNING -- code presumes all but last file take exactly one sector
            uint16_t startCluster = i + 2;

            struct TextFile const * inf = &info[i];
            padded_memcpy(d->name, inf->name, 11);
            d->createTimeFine   = __SECONDS_INT__ % 2 * 100;
            d->createTime       = __DOSTIME__;
            d->createDate       = __DOSDATE__;
            d->lastAccessDate   = __DOSDATE__;
            d->highStartCluster = startCluster >> 16;
            // DIR_WrtTime and DIR_WrtDate must be supported
            d->updateTime       = __DOSTIME__;
            d->updateDate       = __DOSDATE__;
            d->startCluster     = startCluster & 0xFFFF;
            d->size = (inf->content ? strlen(inf->content) : UF2_SIZE);
        }

    } else if (block_no < BPB_TOTAL_SECTORS) {

        sectionIdx -= FS_START_CLUSTERS_SECTOR;
        if (sectionIdx < NUM_FILES - 1) {
            memcpy(data, info[sectionIdx].content, strlen(info[sectionIdx].content));
        } else { // generate the UF2 file data on-the-fly
            sectionIdx -= NUM_FILES - 1;
            uint32_t addr = USER_FLASH_START + (sectionIdx * UF2_FIRMWARE_BYTES_PER_SECTOR);
            if (addr < CFG_UF2_FLASH_SIZE) {
                UF2_Block *bl = (void *)data;
                bl->magicStart0 = UF2_MAGIC_START0;
                bl->magicStart1 = UF2_MAGIC_START1;
                bl->magicEnd = UF2_MAGIC_END;
                bl->blockNo = sectionIdx;
                bl->numBlocks = UF2_SECTORS;
                bl->targetAddr = addr;
                bl->payloadSize = UF2_FIRMWARE_BYTES_PER_SECTOR;
                bl->flags = UF2_FLAG_FAMILYID;
                bl->familyID = CFG_UF2_BOARD_APP_ID;
                memcpy(bl->data, (void *)addr, bl->payloadSize);
            }
        }

    }
}

/*------------------------------------------------------------------*/
/* Write UF2
 *------------------------------------------------------------------*/

/**
 * Write an uf2 block wrapped by 512 sector.
 * @return number of bytes processed, only 3 following values
 *  -1 : if not an uf2 block
 * 512 : write is successful (BPB_SECTOR_SIZE == 512)
 *   0 : is busy with flashing, tinyusb stack will call write_block again with the same parameters later on
 */
static bool erase_bootloader_staging(WriteState* state) {
  if (state->bootloaderStagingErased) {
    return true;
  }

#if defined(MOTA_INTERNAL_BOOTLOADER_UPDATE) || defined(MOTA_SD_BOOTLOADER_UPDATE)
  // Legacy/manual UF2 receives a bootloader at the fixed E0000 scratch range.
  // Internal/SD application layouts do not reserve that range, so a valid
  // application may extend into it. Refuse before the first erase unless its hash-bound
  // EndF proves the complete live image is below the fixed scratch start. A
  // recovery device with no valid app may still receive a bootloader UF2.
  if (state->bootloaderEraseOffset == 0 && bootloader_app_is_valid() &&
      !ota_delta_live_app_fits_below(MOTA_NRF52_BL_SCRATCH_START)) {
    state->aborted = true;
    return false;
  }
#endif

  flash_nrf5x_erase(BOOTLOADER_ADDR_NEW_RECEIVED + state->bootloaderEraseOffset, CODE_PAGE_SIZE);
  state->bootloaderEraseOffset += CODE_PAGE_SIZE;
  if (state->bootloaderEraseOffset < DFU_BL_IMAGE_MAX_SIZE) {
    return false;
  }

  state->bootloaderStagingErased = true;
  return true;
}

static bool prepare_app_block(UF2_Block const* block, WriteState* state) {
  if (state->appEraseInProgress) {
    if (flash_nrf5x_erase_step(state->appEraseAddress, false)) {
      state->appEraseInProgress = false;
    }
    return false;
  }

  uint32_t const page = (block->targetAddr - USER_FLASH_START) / CODE_PAGE_SIZE;
  switch (uf2_app_flash_next_action(&state->appSettingsInvalidated,
                                    state->appErasedMask, page)) {
    case UF2_APP_FLASH_INVALIDATE_SETTINGS: {
      // Fail closed before changing any application or SoftDevice page. The
      // reset boundary in main() has already cleared stale ACL/BPROT state, so
      // this one-way settings write is safe after either direct handoff.
      // Direct app UF2 does not use the legacy page cache; abandon any partial
      // CDC/bootloader staging page before this transfer owns flash state.
      flash_nrf5x_discard();
      flash_nrf5x_invalidate_app_settings();
      return false;
    }

    case UF2_APP_FLASH_ERASE_PAGE:
      // Return busy between short partial-erase steps so TinyUSB can run and an
      // inherited watchdog can be fed. TinyUSB retries this same sector until
      // the page is complete, then once more to program the block.
      state->appEraseAddress = block->targetAddr;
      state->appEraseInProgress = !flash_nrf5x_erase_step(block->targetAddr, true);
      return false;

    case UF2_APP_FLASH_PROGRAM_BLOCK:
      return true;
  }

  return false;
}

int write_block(uint32_t block_no, uint8_t* data, WriteState* state) {
  UF2_Block* block = (void*)data;
  (void)block_no;

  if (state->aborted) {
    return -1;
  }

  if (!is_uf2_block(block)) {
    return -1;
  }

  uint8_t update_kind;
  switch (block->familyID) {
    case CFG_UF2_BOARD_APP_ID:
    case CFG_UF2_FAMILY_APP_ID:
      update_kind = UF2_UPDATE_KIND_APPLICATION;
      break;

    case CFG_UF2_FAMILY_BOOT_ID:
      update_kind = UF2_UPDATE_KIND_BOOTLOADER;
      break;

    default:
      return -1;
  }

  uf2_transfer_result_t const transfer_result =
    uf2_transfer_prepare(block->numBlocks, block->blockNo, update_kind, MAX_BLOCKS,
                         &state->numBlocks, &state->updateKind, &state->aborted,
                         state->writtenMask);
  if (transfer_result == UF2_TRANSFER_ABORTED) {
    return -1;
  }
  if (transfer_result == UF2_TRANSFER_DUPLICATE) {
    bool const destination_matches =
      update_kind != UF2_UPDATE_KIND_APPLICATION ||
      !in_app_space(block->targetAddr) ||
      memcmp((void const*)(uintptr_t)block->targetAddr, block->data,
             block->payloadSize) == 0;
    if (uf2_transfer_validate_duplicate(transfer_result, destination_matches,
                                        &state->aborted) == UF2_TRANSFER_ABORTED) {
      // A different same-geometry application has reused a committed block
      // number. Keep the application invalid and require an explicit MSC
      // session reset before another image can start.
      return -1;
    }

    // Application retransmissions are accepted only when they are already in
    // flash. Bootloader retransmissions can be ignored here because the final
    // board-bound whole-image manifest CRC rejects any mixed staged image.
    return BPB_SECTOR_SIZE;
  }

  switch (update_kind) {
    case UF2_UPDATE_KIND_APPLICATION:

      if (in_app_space(block->targetAddr)) {
        if (!prepare_app_block(block, state)) {
          return 0;
        }

        PRINTF("Write addr = 0x%08lX, block = %ld (%ld of %ld)\r\n", block->targetAddr, block->blockNo,
               state->numWritten, block->numBlocks);
        flash_nrf5x_write_erased(block->targetAddr, block->data, block->payloadSize);
      } else if (block->targetAddr < USER_FLASH_START) {
        PRINTF("skip writing to MBR\r\n");
      } else {
        state->aborted = true;
        return -1;
      }
      break;

    case UF2_UPDATE_KIND_BOOTLOADER:
      PRINTF("addr = 0x%08lX, block = %ld (%ld of %ld)\r\n", block->targetAddr, block->blockNo,
             state->numWritten, block->numBlocks);

      if (in_uicr_space(block->targetAddr)) {
        uint32_t uicr_boot_addr;
        uint32_t uicr_mbr_param;
        memcpy(&uicr_boot_addr, block->data + 0x14, sizeof(uicr_boot_addr));
        memcpy(&uicr_mbr_param, block->data + 0x18, sizeof(uicr_mbr_param));

        if (uicr_boot_addr != BOOTLOADER_ADDR_START ||
            uicr_mbr_param != BOOTLOADER_MBR_PARAMS_PAGE_ADDRESS) {
          PRINTF("Incorrect UICR value\r\n");
          PRINT_HEX(uicr_boot_addr);
          PRINT_HEX(uicr_mbr_param);
          state->aborted = true;
          return -1;
        }
        state->has_uicr = true;
      } else if (in_bootloader_space(block->targetAddr)) {
        if (!erase_bootloader_staging(state)) {
          return 0;
        }

        uint32_t const staging_addr =
          BOOTLOADER_ADDR_NEW_RECEIVED + (block->targetAddr - BOOTLOADER_ADDR_START);
        flash_nrf5x_write(staging_addr, block->data, block->payloadSize, false);
      } else if (block->targetAddr < USER_FLASH_START) {
        PRINTF("skip writing to MBR\r\n");
      } else {
        state->aborted = true;
        return -1;
      }
      break;

    default:
      state->aborted = true;
      return -1;
  }

  uf2_transfer_commit(block->blockNo, &state->numWritten, state->writtenMask);

  if (state->numWritten >= state->numBlocks) {
    bool const update_bootloader = state->updateKind == UF2_UPDATE_KIND_BOOTLOADER;

    if (update_bootloader) {
      // Bootloader UF2 is staged through the legacy 4 KiB page cache.
      flash_nrf5x_flush(false);
      uint32_t const expected_board_id = ((uint32_t)USB_DESC_VID << 16) | USB_DESC_UF2_PID;
      uint8_t const* staged_image = (uint8_t const*)(uintptr_t)BOOTLOADER_ADDR_NEW_RECEIVED;
      extern const bootloader_update_envelope_t bootloaderUpdateManifest;
      if (!state->has_uicr || !state->bootloaderStagingErased ||
          !bootloader_image_validate(staged_image, BOOTLOADER_ADDR_START, DFU_BL_IMAGE_MAX_SIZE,
                                     expected_board_id,
                                     bootloaderUpdateManifest.manifest.device_name)) {
        PRINTF("Bootloader image validation failed\r\n");
        state->aborted = true;
      }
    } else {
      // Application UF2 programs erased pages directly in 256-byte blocks.
      // Never flush a cache that may belong to an abandoned CDC transfer.
      flash_nrf5x_discard();
      if (!state->appSettingsInvalidated) {
        state->aborted = true;
      }
    }
  }

  return BPB_SECTOR_SIZE;
}
