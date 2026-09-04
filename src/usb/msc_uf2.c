/*
 * The MIT License (MIT)
 *
 * Copyright (c) 2018 Ha Thach for Adafruit Industries
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

#include "tusb.h"
#include "uf2/uf2.h"
#include "uf2/uf2_transfer_state.h"
#include "flash_nrf5x.h"
#include "app_timer.h"
#include "boards.h"
#include "crc16.h"
#include "nrf_wdt.h"

#if CFG_TUD_MSC

#include "bootloader.h"

/*------------------------------------------------------------------*/
/* MACRO TYPEDEF CONSTANT ENUM
 *------------------------------------------------------------------*/

/*------------------------------------------------------------------*/
/* UF2
 *------------------------------------------------------------------*/
static WriteState _wr_state = { 0 };
static bool _first_write = true;
static bool _app_completion_pending = false;
static bool _app_completion_after_eject = false;
static bool _app_msc_command_active = false;
static uint32_t _app_completion_last_activity = 0;

#define UF2_APP_COMPLETION_IDLE_MS 1000u
#define UF2_APP_COMPLETION_IDLE_TICKS APP_TIMER_TICKS(UF2_APP_COMPLETION_IDLE_MS)

APP_TIMER_DEF(_app_completion_timer);

void read_block(uint32_t block_no, uint8_t *data);
int  write_block(uint32_t block_no, uint8_t *data, WriteState *state);

static void complete_app_update(void)
{
  if (!_wr_state.appValidated || _wr_state.appSize == 0)
  {
    _wr_state.aborted = true;
    return;
  }

  uint16_t app_crc = 0;
  uint32_t offset = 0;
  while (offset < _wr_state.appSize)
  {
    uint32_t const remaining = _wr_state.appSize - offset;
    uint32_t const chunk = remaining > CODE_PAGE_SIZE ? CODE_PAGE_SIZE : remaining;
    app_crc = crc16_compute((uint8_t const*)(uintptr_t)(_wr_state.appStart + offset),
                            chunk, offset == 0 ? NULL : &app_crc);
    if (nrf_wdt_started(NRF_WDT))
    {
      uint32_t const enabled_channels = NRF_WDT->RREN;
      for (uint8_t channel = 0; channel < 8; channel++)
      {
        if (enabled_channels & (1UL << channel))
        {
          nrf_wdt_reload_request_set(NRF_WDT, channel);
        }
      }
    }
    board_watchdog_feed();
    offset += chunk;
  }

  dfu_update_status_t update_status;
  memset(&update_status, 0, sizeof(dfu_update_status_t));
  update_status.status_code = DFU_UPDATE_APP_COMPLETE;
  update_status.app_crc = app_crc;
  update_status.app_size = _wr_state.appSize;

  PRINTF("Application update complete\r\n");
  bootloader_dfu_update_process(update_status);
  led_state(STATE_WRITING_FINISHED);
}

static bool take_pending_app_completion(void)
{
  bool const can_complete = _app_completion_pending && !_wr_state.aborted;

  _app_completion_pending = false;
  _app_completion_after_eject = false;
  return can_complete;
}

static void app_completion_timer_handler(void *context)
{
  (void) context;

  if (!_app_completion_pending)
  {
    return;
  }

  uint32_t const now = app_timer_cnt_get();
  if (_app_msc_command_active)
  {
    // The MSC lifecycle begins at acceptance of every valid CBW and ends only
    // after its CSW reaches the host. This covers delayed WRITE10 data, READ10,
    // built-in commands, and application-provided SCSI commands uniformly.
    // Never let the idle fallback reset in the middle of any of them.
    _app_completion_last_activity = now;
    APP_ERROR_CHECK(app_timer_start(_app_completion_timer,
                                    UF2_APP_COMPLETION_IDLE_TICKS,
                                    NULL));
    return;
  }

  uint32_t const idle_ticks =
    app_timer_cnt_diff_compute(now, _app_completion_last_activity);
  if (idle_ticks + APP_TIMER_MIN_TIMEOUT_TICKS < UF2_APP_COMPLETION_IDLE_TICKS)
  {
    APP_ERROR_CHECK(app_timer_start(_app_completion_timer,
                                    UF2_APP_COMPLETION_IDLE_TICKS - idle_ticks,
                                    NULL));
    return;
  }

  if (take_pending_app_completion())
  {
    complete_app_update();
  }
}

static void defer_app_completion(void)
{
  _app_completion_last_activity = app_timer_cnt_get();
  if (_app_completion_pending)
  {
    return;
  }

  _app_completion_pending = true;
  APP_ERROR_CHECK(app_timer_start(_app_completion_timer,
                                  UF2_APP_COMPLETION_IDLE_TICKS,
                                  NULL));
}

void uf2_write_session_init(void)
{
  APP_ERROR_CHECK(app_timer_create(&_app_completion_timer, APP_TIMER_MODE_SINGLE_SHOT,
                                   app_completion_timer_handler));
  uf2_write_session_reset();
}

void uf2_write_session_reset(void)
{
  // Only bootloader UF2 owns the legacy 4 KiB staging cache. An unrelated MSC
  // mount/eject must not discard a partial CDC serial-DFU page.
  if (_wr_state.updateKind == UF2_UPDATE_KIND_BOOTLOADER)
  {
    flash_nrf5x_discard();
  }
  uf2_transfer_reset(&_wr_state, sizeof(_wr_state));
  _first_write = true;
  _app_completion_pending = false;
  _app_completion_after_eject = false;
  _app_msc_command_active = false;
}

void uf2_write_session_close(void)
{
  if (take_pending_app_completion())
  {
    complete_app_update();
  }
  uf2_write_session_reset();
}

// TinyUSB invokes these around every valid MSC command, including READ10,
// WRITE10, built-in commands, and application-provided SCSI commands. Tracking
// the complete CBW-to-CSW lifetime closes the idle-timer race left by tracking
// only individual data callbacks.
void tud_msc_command_begin_cb(uint8_t lun, uint8_t const scsi_cmd[16])
{
  (void) lun;
  (void) scsi_cmd;

  _app_msc_command_active = true;
  if (_app_completion_pending)
  {
    _app_completion_last_activity = app_timer_cnt_get();
  }
}

void tud_msc_command_complete_cb(uint8_t lun, uint8_t const scsi_cmd[16])
{
  (void) lun;
  (void) scsi_cmd;

  _app_msc_command_active = false;
  if (_app_completion_pending)
  {
    _app_completion_last_activity = app_timer_cnt_get();
  }
}

void tud_msc_reset_cb(void)
{
  // BOT/bus reset abandons an in-flight command without a CSW. It is not
  // permission to bless an image or honor a half-completed eject, but it must
  // release the lifecycle guard so a completed image can reach a fresh idle
  // boundary while the cable remains connected.
  _app_msc_command_active = false;
  _app_completion_after_eject = false;
  if (_app_completion_pending)
  {
    _app_completion_last_activity = app_timer_cnt_get();
  }
}

//--------------------------------------------------------------------+
// tinyusb callbacks
//--------------------------------------------------------------------+

// Invoked when received SCSI_CMD_INQUIRY
// Application fill vendor id, product id and revision with string up to 8, 16, 4 characters respectively
void tud_msc_inquiry_cb(uint8_t lun, uint8_t vendor_id[8], uint8_t product_id[16], uint8_t product_rev[4])
{
  (void) lun;

  const char vid[] = "Adafruit";
  const char pid[] = "nRF UF2";
  const char rev[] = "1.0";

  memcpy(vendor_id  , vid, strlen(vid));
  memcpy(product_id , pid, strlen(pid));
  memcpy(product_rev, rev, strlen(rev));
}

// Invoked when received Test Unit Ready command.
// return true allowing host to read/write this LUN e.g SD card inserted
bool tud_msc_test_unit_ready_cb(uint8_t lun)
{
  (void) lun;
  return true;
}

// Callback invoked when received an SCSI command not in built-in list below
// - READ_CAPACITY10, READ_FORMAT_CAPACITY, INQUIRY, MODE_SENSE6, REQUEST_SENSE
// - READ10 and WRITE10 has their own callbacks
int32_t tud_msc_scsi_cb (uint8_t lun, uint8_t const scsi_cmd[16], void* buffer, uint16_t bufsize)
{
  void const* response = NULL;
  uint16_t resplen = 0;

  // most scsi handled is input
  bool in_xfer = true;

  switch (scsi_cmd[0])
  {
    case SCSI_CMD_PREVENT_ALLOW_MEDIUM_REMOVAL:
      // Host is about to read/write etc ... better not to disconnect disk
      resplen = 0;
    break;

    case 0x35: // SCSI SYNCHRONIZE CACHE (10)
      // A Linux filesystem sync can issue this while other virtual-FAT bios
      // remain queued. It is activity, not permission to disconnect. Start a
      // fresh idle interval only after TinyUSB has returned this command's CSW.
      resplen = 0;
    break;

    default:
      // Set Sense = Invalid Command Operation
      tud_msc_set_sense(lun, SCSI_SENSE_ILLEGAL_REQUEST, 0x20, 0x00);

      // negative means error -> tinyusb could stall and/or response with failed status
      resplen = -1;
    break;
  }

  // return resplen must not larger than bufsize
  if ( resplen > bufsize ) resplen = bufsize;

  if ( response && (resplen > 0) )
  {
    if(in_xfer)
    {
      memcpy(buffer, response, resplen);
    }else
    {
      // SCSI output
    }
  }

  return resplen;
}

// Callback invoked when received READ10 command.
// Copy disk's data to buffer (up to bufsize) and return number of copied bytes.
int32_t tud_msc_read10_cb (uint8_t lun, uint32_t lba, uint32_t offset, void* buffer, uint32_t bufsize)
{
  (void) lun;
  memset(buffer, 0, bufsize);

  // since we return block size each, offset should always be zero
  TU_ASSERT(offset == 0, -1);

  uint32_t count = 0;

  while ( count < bufsize )
  {
    read_block(lba, buffer);

    lba++;
    buffer += 512;
    count  += 512;
  }

  return count;
}

// Callback invoked when received WRITE10 command.
// Process data in buffer to disk's storage and return number of written bytes
int32_t tud_msc_write10_cb (uint8_t lun, uint32_t lba, uint32_t offset, uint8_t* buffer, uint32_t bufsize)
{
  (void) lun;

  TU_ASSERT(offset == 0, -1);

  uint32_t count = 0;

  while ( count < bufsize )
  {
    int written;

    // Consider non-uf2 block write as successful
    // only break if write_block is busy with flashing (return 0)
    written = write_block(lba, buffer, &_wr_state);
    if (_wr_state.aborted)
    {
      // A malformed or conflicting transfer is terminal until an explicit MSC
      // reset boundary. Stop before another sector in this 4 KiB buffer can
      // erase or program flash, and fail the current WRITE10 command.
      return -1;
    }
    if ( written > 0 )
    {
      bootloader_dfu_activity_mark();
    }
    else if ( written == 0 )
    {
      break;
    }

    lba++;
    buffer += 512;
    count  += 512;
  }

  return count;
}

// Callback invoked when WRITE10 command is completed (status received and accepted by host).
void tud_msc_write10_complete_cb(uint8_t lun)
{
  // abort the DFU, uf2 block failed integrity check
  if ( _wr_state.aborted )
  {
    // aborted and reset
    PRINTF("Aborted\r\n");

    _app_completion_pending = false;
    _app_completion_after_eject = false;

    dfu_update_status_t update_status;
    memset(&update_status, 0, sizeof(dfu_update_status_t ));
    update_status.status_code = DFU_RESET;
    update_status.restart_into_bootloader = false;

    bootloader_dfu_update_process(update_status);

    led_state(STATE_WRITING_FINISHED);
  }
  else if ( _wr_state.numBlocks )
  {
    // Start LED writing pattern with first write
    if (_first_write)
    {
      _first_write = false;
      led_state(STATE_WRITING_STARTED);
    }

    // All block of uf2 file is complete --> complete DFU process
    if (_wr_state.numWritten >= _wr_state.numBlocks)
    {
      dfu_update_status_t update_status;
      memset(&update_status, 0, sizeof(dfu_update_status_t ));

      if ( _wr_state.updateKind == UF2_UPDATE_KIND_BOOTLOADER )
      {
        // update bootloader always end with reset
        update_status.status_code = DFU_RESET;
        update_status.restart_into_bootloader = false;

        // Location of current stored new bootloader
        uint32_t * new_bootloader = (uint32_t *) BOOTLOADER_ADDR_NEW_RECEIVED;

        PRINT_HEX(new_bootloader);

        // skip if there is no bootloader change
        if ( memcmp(new_bootloader, (uint8_t*) BOOTLOADER_ADDR_START, DFU_BL_IMAGE_MAX_SIZE) )
        {
          PRINTF("Coyping new bootloader\r\n");

          sd_mbr_command_t command =
          {
            .command = SD_MBR_COMMAND_COPY_BL,
            .params.copy_bl.bl_src = new_bootloader,
            .params.copy_bl.bl_len = DFU_BL_IMAGE_MAX_SIZE/4 // size in words
          };

          // on success, COPY_BL won't return but run the new bootloader right away.
          sd_mbr_command(&command);
        }

        PRINTF("bootloader update complete\r\n");
      }else
      {
        // The final WRITE10 status has reached the host, but Linux can still
        // issue FAT metadata writes or SYNCHRONIZE CACHE from cp/sync. Keep the
        // completed image invalid for a short idle window, or until an explicit
        // eject status has itself completed, so reset cannot turn sync into
        // EIO. Bootloader-family UF2 retains its immediate COPY_BL path.
        defer_app_completion();
        return;
      }

      bootloader_dfu_update_process(update_status);

      led_state(STATE_WRITING_FINISHED);
    }
  }
}

// Invoked after TinyUSB has sent and the host has accepted a non-READ/WRITE
// SCSI status. A cache sync merely restarts the idle interval; an explicit
// media eject is permission to complete immediately after its status.
void tud_msc_scsi_complete_cb(uint8_t lun, uint8_t const scsi_cmd[16])
{
  (void) lun;

  if (scsi_cmd[0] == 0x35)
  {
    return;
  }

  if (_app_completion_after_eject &&
      scsi_cmd[0] == SCSI_CMD_START_STOP_UNIT &&
      take_pending_app_completion())
  {
    complete_app_update();
  }
}

// Invoked when received SCSI_CMD_READ_CAPACITY_10 and SCSI_CMD_READ_FORMAT_CAPACITY to determine the disk size
// Application update block count and block size
void tud_msc_capacity_cb(uint8_t lun, uint32_t* block_count, uint16_t* block_size)
{
  (void) lun;

  *block_count = CFG_UF2_NUM_BLOCKS;
  *block_size  = 512;
}

// Invoked when received Start Stop Unit command
// - Start = 0 : stopped power mode, if load_eject = 1 : unload disk storage
// - Start = 1 : active mode, if load_eject = 1 : load disk storage
bool tud_msc_start_stop_cb(uint8_t lun, uint8_t power_condition, bool start, bool load_eject)
{
  (void) lun;
  (void) power_condition;

  if ( load_eject )
  {
    if (start)
    {
      // load disk storage
    }else
    {
      // unload disk storage
      if (_app_completion_pending)
      {
        // tud_msc_scsi_complete_cb() will run after the eject status reaches
        // the host, then complete the application update exactly once.
        _app_completion_after_eject = true;
      }
      else
      {
        uf2_write_session_reset();
      }
    }
  }

  return true;
}

#endif
