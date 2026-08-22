#include <stdalign.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "nrf_error.h"
#include "nrf_soc.h"
#include "pstorage.h"

#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))

static uint32_t          erase_results[32];
static uint32_t          write_results[32];
static uint32_t          erase_pages[64];
static uintptr_t         write_destinations[64];
static uint32_t          write_values[64];
static unsigned          erase_result_count;
static unsigned          write_result_count;
static unsigned          erase_calls;
static unsigned          write_calls;
static unsigned          callback_calls;
static uint8_t           callback_ops[64];
static uint32_t          callback_results[64];
static uint32_t          callback_blocks[64];
static uint8_t          *callback_data[64];
static uint32_t          callback_sizes[64];
static bool              nested_clear_enabled;
static bool              nested_clear_done;
static pstorage_handle_t nested_clear_handle;
static uint32_t          nested_clear_result;
static bool              nested_store_enabled;
static bool              nested_store_done;
static pstorage_handle_t nested_store_handle;
static uint8_t          *nested_store_data;
static uint8_t          *nested_store_trigger_data;
static uint32_t          nested_store_size;
static uint32_t          nested_store_offset;
static uint32_t          nested_store_result;

static uint32_t next_result(const uint32_t *results, unsigned count, unsigned call_index) {
  return call_index < count ? results[call_index] : NRF_SUCCESS;
}

uint32_t sd_flash_page_erase(uint32_t page_number) {
  if (erase_calls < ARRAY_SIZE(erase_pages)) {
    erase_pages[erase_calls] = page_number;
  }
  uint32_t result = next_result(erase_results, erase_result_count, erase_calls);
  erase_calls++;
  return result;
}

uint32_t sd_flash_write(uint32_t *dst, const uint32_t *src, uint32_t size) {
  if (write_calls < ARRAY_SIZE(write_destinations)) {
    write_destinations[write_calls] = (uintptr_t)dst;
    write_values[write_calls]       = size > 0u ? src[0] : 0u;
  }
  (void)src;
  (void)size;
  uint32_t result = next_result(write_results, write_result_count, write_calls);
  write_calls++;
  return result;
}

static void callback(pstorage_handle_t *handle, uint8_t op, uint32_t result, uint8_t *data, uint32_t size) {
  if (callback_calls >= ARRAY_SIZE(callback_ops)) {
    fputs("too many callbacks\n", stderr);
    exit(2);
  }
  callback_ops[callback_calls]     = op;
  callback_results[callback_calls] = result;
  callback_blocks[callback_calls]  = handle->block_id;
  callback_data[callback_calls]    = data;
  callback_sizes[callback_calls]   = size;
  callback_calls++;

  if (nested_clear_enabled && !nested_clear_done) {
    nested_clear_done   = true;
    nested_clear_result = pstorage_clear(&nested_clear_handle, 4096u);
  }

  if (nested_store_enabled && !nested_store_done && data == nested_store_trigger_data) {
    nested_store_done = true;
    nested_store_result =
      pstorage_store(&nested_store_handle, nested_store_data, nested_store_size, nested_store_offset);
  }
}

static pstorage_handle_t reset_and_register(uint32_t address) {
  pstorage_handle_t       handle = {0};
  pstorage_module_param_t params = {.cb = callback};
  if (pstorage_init() != NRF_SUCCESS || pstorage_register(&params, &handle) != NRF_SUCCESS) {
    fputs("setup failed\n", stderr);
    exit(2);
  }
  handle.block_id    = address;
  erase_result_count = write_result_count = 0;
  erase_calls = write_calls = callback_calls = 0;
  nested_clear_enabled                       = false;
  nested_clear_done                          = false;
  nested_clear_handle                        = handle;
  nested_clear_result                        = UINT32_MAX;
  nested_store_enabled                       = false;
  nested_store_done                          = false;
  nested_store_handle                        = handle;
  nested_store_data                          = NULL;
  nested_store_trigger_data                  = NULL;
  nested_store_size                          = 0;
  nested_store_offset                        = 0;
  nested_store_result                        = UINT32_MAX;
  dfu_page_erased                            = NULL;
  dfu_image_page_count                       = 0;
  dfu_base_address                           = 0;
  return handle;
}

static int busy_success_retry_test(void) {
  pstorage_handle_t handle = reset_and_register(0x00030000u);
  erase_results[0]         = NRF_ERROR_BUSY;
  erase_results[1]         = NRF_SUCCESS;
  erase_result_count       = 2;

  if (pstorage_clear(&handle, 4096u) != NRF_SUCCESS || erase_calls != 1u) {
    return 10;
  }

  /* This completion belongs to the operation that caused BUSY. */
  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (erase_calls != 2u || callback_calls != 0u) {
    return 11;
  }

  /* Only this event belongs to the retried pstorage request. */
  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (erase_calls != 2u || callback_calls != 1u || callback_ops[0] != PSTORAGE_CLEAR_OP_CODE ||
      callback_results[0] != NRF_SUCCESS) {
    return 12;
  }

  /* An unrelated event while idle must remain ignored. */
  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  return callback_calls == 1u ? 0 : 13;
}

static int repeated_busy_foreign_error_test(void) {
  pstorage_handle_t handle = reset_and_register(0x00031000u);
  erase_results[0]         = NRF_ERROR_BUSY;
  erase_results[1]         = NRF_ERROR_BUSY;
  erase_results[2]         = NRF_SUCCESS;
  erase_result_count       = 3;

  if (pstorage_clear(&handle, 4096u) != NRF_SUCCESS || erase_calls != 1u) {
    return 20;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (erase_calls != 2u || callback_calls != 0u) {
    return 21;
  }

  /* Even an ERROR event is foreign while waiting after BUSY. */
  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_ERROR);
  if (erase_calls != 3u || callback_calls != 0u) {
    return 22;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  return callback_calls == 1u && callback_results[0] == NRF_SUCCESS ? 0 : 23;
}

static int queued_clear_store_test(void) {
  alignas(4) uint32_t settings[8] = {0};
  pstorage_handle_t   handle      = reset_and_register(0x000FF000u);
  erase_results[0]                = NRF_ERROR_BUSY;
  erase_results[1]                = NRF_SUCCESS;
  erase_result_count              = 2;
  write_results[0]                = NRF_SUCCESS;
  write_result_count              = 1;

  if (pstorage_clear(&handle, sizeof(settings)) != NRF_SUCCESS ||
      pstorage_store(&handle, (uint8_t *)settings, sizeof(settings), 0u) != NRF_SUCCESS || erase_calls != 1u ||
      write_calls != 0u) {
    return 30;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (erase_calls != 2u || write_calls != 0u || callback_calls != 0u) {
    return 31;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (write_calls != 1u || callback_calls != 1u || callback_ops[0] != PSTORAGE_CLEAR_OP_CODE) {
    return 32;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  return callback_calls == 2u && callback_ops[1] == PSTORAGE_STORE_OP_CODE ? 0 : 33;
}

static int lazy_busy_completion_test(void) {
  alignas(4) uint32_t word      = 0x12345678u;
  uint8_t             erased[1] = {0};
  pstorage_handle_t   handle    = reset_and_register(0x00026000u);
  dfu_base_address              = handle.block_id;
  dfu_image_page_count          = 1u;
  dfu_page_erased               = erased;
  erase_results[0]              = NRF_ERROR_BUSY;
  erase_results[1]              = NRF_SUCCESS;
  erase_result_count            = 2;
  write_results[0]              = NRF_SUCCESS;
  write_result_count            = 1;

  if (pstorage_store(&handle, (uint8_t *)&word, sizeof(word), 0u) != NRF_SUCCESS || erase_calls != 1u) {
    return 40;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (erase_calls != 2u || callback_calls != 0u || erased[0] != 0u) {
    return 41;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (erased[0] != 1u || write_calls != 1u || callback_calls != 0u) {
    return 42;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  return callback_calls == 1u && callback_ops[0] == PSTORAGE_STORE_OP_CODE && callback_results[0] == NRF_SUCCESS &&
             callback_data[0] == (uint8_t *)&word && callback_sizes[0] == sizeof(word)
           ? 0
           : 43;
}

static int lazy_queue_full_error_test(void) {
  alignas(4) uint32_t word      = 0;
  uint8_t             erased[1] = {0};
  pstorage_handle_t   handle    = reset_and_register(0x00032000u);
  erase_result_count            = 0; /* All accepted. */

  for (unsigned i = 0; i < 18u; i++) {
    if (pstorage_clear(&handle, 4096u) != NRF_SUCCESS) {
      return 50;
    }
  }
  if (erase_calls != 1u) {
    return 51;
  }

  dfu_base_address     = 0x00026000u;
  dfu_image_page_count = 1u;
  dfu_page_erased      = erased;
  handle.block_id      = dfu_base_address;
  if (pstorage_store(&handle, (uint8_t *)&word, sizeof(word), 0u) != NRF_ERROR_NO_MEM) {
    return 52;
  }

  /* Drain the unrelated queue, then prove the failed lazy enqueue did not stick active. */
  for (unsigned i = 0; i < 18u; i++) {
    pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  }
  if (callback_calls != 18u || erase_calls != 18u) {
    return 53;
  }

  if (pstorage_store(&handle, (uint8_t *)&word, sizeof(word), 0u) != NRF_SUCCESS || erase_calls != 19u) {
    return 54;
  }

  return 0;
}

static int pending_lazy_error_callback_test(void) {
  alignas(4) uint32_t words[3]  = {0x11111111u, 0x22222222u, 0x33333333u};
  uint8_t             erased[3] = {0, 0, 0};
  pstorage_handle_t   handle    = reset_and_register(0x00026000u);
  dfu_base_address              = handle.block_id;
  dfu_image_page_count          = 3u;
  dfu_page_erased               = erased;
  erase_results[0]              = NRF_SUCCESS;
  erase_results[1]              = NRF_ERROR_FORBIDDEN;
  erase_result_count            = 2;
  write_results[0]              = NRF_SUCCESS;
  write_result_count            = 1;

  if (pstorage_store(&handle, (uint8_t *)&words[0], 4u, 0u) != NRF_SUCCESS ||
      pstorage_store(&handle, (uint8_t *)&words[1], 4u, 4096u) != NRF_SUCCESS ||
      pstorage_store(&handle, (uint8_t *)&words[2], 4u, 8192u) != NRF_SUCCESS) {
    return 60;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (erased[0] != 1u || write_calls != 1u) {
    return 61;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (erase_calls != 2u || callback_calls != 3u) {
    return 62;
  }
  if (callback_results[0] != NRF_SUCCESS || callback_data[0] != (uint8_t *)&words[0] ||
      callback_results[1] != NRF_ERROR_FORBIDDEN || callback_data[1] != (uint8_t *)&words[1] ||
      callback_results[2] != NRF_ERROR_FORBIDDEN || callback_data[2] != (uint8_t *)&words[2]) {
    return 63;
  }

  pstorage_handle_t recovery = handle;
  recovery.block_id          = 0x00039000u;
  erase_results[2]           = NRF_SUCCESS;
  erase_result_count         = 3;
  if (pstorage_clear(&recovery, 4096u) != NRF_SUCCESS || erase_calls != 3u ||
      erase_pages[2] != recovery.block_id / 4096u) {
    return 64;
  }
  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (callback_calls != 4u || callback_ops[3] != PSTORAGE_CLEAR_OP_CODE || callback_blocks[3] != recovery.block_id ||
      callback_results[3] != NRF_SUCCESS) {
    return 65;
  }

  return 0;
}

static int initial_lazy_error_test(void) {
  alignas(4) uint32_t word      = 0;
  uint8_t             erased[1] = {0};
  pstorage_handle_t   handle    = reset_and_register(0x00026000u);
  dfu_base_address              = handle.block_id;
  dfu_image_page_count          = 1u;
  dfu_page_erased               = erased;
  erase_results[0]              = NRF_ERROR_FORBIDDEN;
  erase_result_count            = 1;

  if (pstorage_store(&handle, (uint8_t *)&word, sizeof(word), 0u) != NRF_ERROR_FORBIDDEN) {
    return 70;
  }

  pstorage_handle_t recovery = handle;
  recovery.block_id          = 0x0003A000u;
  erase_results[1]           = NRF_SUCCESS;
  erase_result_count         = 2;
  if (pstorage_clear(&recovery, 4096u) != NRF_SUCCESS || erase_calls != 2u ||
      erase_pages[1] != recovery.block_id / 4096u) {
    return 71;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  return callback_calls == 1u && callback_blocks[0] == recovery.block_id && callback_results[0] == NRF_SUCCESS ? 0 : 72;
}

static int busy_retry_fatal_recovery_test(void) {
  pstorage_handle_t first  = reset_and_register(0x0003B000u);
  pstorage_handle_t second = first;
  second.block_id          = 0x0003C000u;
  erase_results[0]         = NRF_ERROR_BUSY;
  erase_results[1]         = NRF_ERROR_FORBIDDEN;
  erase_results[2]         = NRF_SUCCESS;
  erase_result_count       = 3;

  if (pstorage_clear(&first, 4096u) != NRF_SUCCESS || erase_calls != 1u) {
    return 80;
  }
  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (erase_calls != 2u || callback_calls != 1u || callback_blocks[0] != first.block_id ||
      callback_results[0] != NRF_ERROR_FORBIDDEN) {
    return 81;
  }

  if (pstorage_clear(&second, 4096u) != NRF_SUCCESS || erase_calls != 3u || erase_pages[2] != second.block_id / 4096u) {
    return 82;
  }
  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  return callback_calls == 2u && callback_blocks[1] == second.block_id && callback_results[1] == NRF_SUCCESS ? 0 : 83;
}

static int owned_event_error_recovery_test(void) {
  pstorage_handle_t first  = reset_and_register(0x0003D000u);
  pstorage_handle_t second = first;
  second.block_id          = 0x0003E000u;

  if (pstorage_clear(&first, 4096u) != NRF_SUCCESS || erase_calls != 1u) {
    return 90;
  }
  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_ERROR);
  if (callback_calls != 1u || callback_blocks[0] != first.block_id || callback_results[0] != NRF_ERROR_TIMEOUT) {
    return 91;
  }

  if (pstorage_clear(&second, 4096u) != NRF_SUCCESS || erase_calls != 2u || erase_pages[1] != second.block_id / 4096u) {
    return 92;
  }
  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  return callback_calls == 2u && callback_blocks[1] == second.block_id && callback_results[1] == NRF_SUCCESS ? 0 : 93;
}

static int full_queue_nested_enqueue_test(void) {
  pstorage_handle_t handle = reset_and_register(0x00040000u);

  for (unsigned i = 0; i < 18u; i++) {
    handle.block_id = 0x00040000u + (i * 4096u);
    if (pstorage_clear(&handle, 4096u) != NRF_SUCCESS) {
      return 100;
    }
  }
  if (erase_calls != 1u) {
    return 101;
  }

  nested_clear_handle          = handle;
  nested_clear_handle.block_id = 0x00060000u;
  nested_clear_enabled         = true;
  for (unsigned i = 0; i < 19u; i++) {
    pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  }

  if (!nested_clear_done || nested_clear_result != NRF_SUCCESS || erase_calls != 19u || callback_calls != 19u ||
      erase_pages[18] != nested_clear_handle.block_id / 4096u || callback_blocks[18] != nested_clear_handle.block_id) {
    return 102;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  return callback_calls == 19u ? 0 : 103;
}

static int nested_enqueue_error_attribution_test(void) {
  pstorage_handle_t first  = reset_and_register(0x00061000u);
  pstorage_handle_t second = first;
  second.block_id          = 0x00062000u;
  erase_results[0]         = NRF_SUCCESS;
  erase_results[1]         = NRF_ERROR_FORBIDDEN;
  erase_results[2]         = NRF_SUCCESS;
  erase_result_count       = 3;

  if (pstorage_clear(&first, 4096u) != NRF_SUCCESS || pstorage_clear(&second, 4096u) != NRF_SUCCESS) {
    return 110;
  }

  nested_clear_handle          = first;
  nested_clear_handle.block_id = 0x00063000u;
  nested_clear_enabled         = true;
  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);

  if (nested_clear_result != NRF_SUCCESS || erase_calls != 3u || callback_calls != 2u ||
      callback_blocks[0] != first.block_id || callback_results[0] != NRF_SUCCESS ||
      callback_blocks[1] != second.block_id || callback_results[1] != NRF_ERROR_FORBIDDEN ||
      erase_pages[2] != nested_clear_handle.block_id / 4096u) {
    return 111;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  return callback_calls == 3u && callback_blocks[2] == nested_clear_handle.block_id &&
             callback_results[2] == NRF_SUCCESS
           ? 0
           : 112;
}

static int lazy_erase_identity_test(void) {
  alignas(4) uint32_t word      = 0xA5A5A5A5u;
  uint8_t             erased[1] = {0};
  pstorage_handle_t   ordinary  = reset_and_register(0x00064000u);
  pstorage_handle_t   app       = ordinary;
  app.block_id                  = 0x00026000u;
  dfu_base_address              = app.block_id;
  dfu_image_page_count          = 1u;
  dfu_page_erased               = erased;

  if (pstorage_clear(&ordinary, 4096u) != NRF_SUCCESS ||
      pstorage_store(&app, (uint8_t *)&word, sizeof(word), 0u) != NRF_SUCCESS) {
    return 120;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (erase_calls != 2u || erased[0] != 0u || callback_calls != 1u || callback_ops[0] != PSTORAGE_CLEAR_OP_CODE ||
      callback_blocks[0] != ordinary.block_id) {
    return 121;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (erased[0] != 1u || write_calls != 1u || callback_calls != 1u) {
    return 122;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  return callback_calls == 2u && callback_ops[1] == PSTORAGE_STORE_OP_CODE && callback_blocks[1] == app.block_id &&
             callback_data[1] == (uint8_t *)&word
           ? 0
           : 123;
}

static int pending_store_event_error_test(void) {
  alignas(4) uint32_t words[2]  = {0xABCD0001u, 0xABCD0002u};
  uint8_t             erased[2] = {0, 0};
  pstorage_handle_t   handle    = reset_and_register(0x00026000u);
  dfu_base_address              = handle.block_id;
  dfu_image_page_count          = 2u;
  dfu_page_erased               = erased;

  if (pstorage_store(&handle, (uint8_t *)&words[0], 4u, 0u) != NRF_SUCCESS ||
      pstorage_store(&handle, (uint8_t *)&words[1], 4u, 4096u) != NRF_SUCCESS) {
    return 130;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (write_calls != 1u || callback_calls != 0u) {
    return 131;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_ERROR);
  if (callback_calls != 2u || callback_results[0] != NRF_ERROR_TIMEOUT || callback_ops[0] != PSTORAGE_STORE_OP_CODE ||
      callback_data[0] != (uint8_t *)&words[0] || callback_sizes[0] != 4u || callback_results[1] != NRF_ERROR_TIMEOUT ||
      callback_ops[1] != PSTORAGE_STORE_OP_CODE || callback_data[1] != (uint8_t *)&words[1] ||
      callback_sizes[1] != 4u) {
    return 132;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  pstorage_handle_t recovery = handle;
  recovery.block_id          = 0x00065000u;
  if (pstorage_clear(&recovery, 4096u) != NRF_SUCCESS || erase_calls != 2u ||
      erase_pages[1] != recovery.block_id / 4096u) {
    return 133;
  }
  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  return callback_calls == 3u && callback_blocks[2] == recovery.block_id && callback_results[2] == NRF_SUCCESS ? 0
                                                                                                               : 134;
}

static int pending_store_immediate_error_test(void) {
  alignas(4) uint32_t words[2]  = {0xDCBA0001u, 0xDCBA0002u};
  uint8_t             erased[2] = {0, 0};
  pstorage_handle_t   handle    = reset_and_register(0x00026000u);
  dfu_base_address              = handle.block_id;
  dfu_image_page_count          = 2u;
  dfu_page_erased               = erased;
  write_results[0]              = NRF_ERROR_FORBIDDEN;
  write_result_count            = 1;

  if (pstorage_store(&handle, (uint8_t *)&words[0], 4u, 0u) != NRF_SUCCESS ||
      pstorage_store(&handle, (uint8_t *)&words[1], 4u, 4096u) != NRF_SUCCESS) {
    return 140;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (write_calls != 1u || callback_calls != 2u || callback_results[0] != NRF_ERROR_FORBIDDEN ||
      callback_ops[0] != PSTORAGE_STORE_OP_CODE || callback_data[0] != (uint8_t *)&words[0] ||
      callback_sizes[0] != 4u || callback_results[1] != NRF_ERROR_FORBIDDEN ||
      callback_ops[1] != PSTORAGE_STORE_OP_CODE || callback_data[1] != (uint8_t *)&words[1] ||
      callback_sizes[1] != 4u) {
    return 141;
  }

  pstorage_handle_t recovery = handle;
  recovery.block_id          = 0x00066000u;
  if (pstorage_clear(&recovery, 4096u) != NRF_SUCCESS || erase_calls != 2u ||
      erase_pages[1] != recovery.block_id / 4096u) {
    return 142;
  }
  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  return callback_calls == 3u && callback_blocks[2] == recovery.block_id && callback_results[2] == NRF_SUCCESS ? 0
                                                                                                               : 143;
}

static int multi_page_clear_test(void) {
  pstorage_handle_t handle = reset_and_register(0x00067000u);

  if (pstorage_clear(&handle, 3u * 4096u) != NRF_SUCCESS || erase_calls != 1u ||
      erase_pages[0] != handle.block_id / 4096u) {
    return 150;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (erase_calls != 2u || erase_pages[1] != (handle.block_id / 4096u) + 1u || callback_calls != 0u) {
    return 151;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (erase_calls != 3u || erase_pages[2] != (handle.block_id / 4096u) + 2u || callback_calls != 0u) {
    return 152;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  return callback_calls == 1u && callback_ops[0] == PSTORAGE_CLEAR_OP_CODE && callback_blocks[0] == handle.block_id &&
             callback_results[0] == NRF_SUCCESS
           ? 0
           : 153;
}

static int pending_same_address_nested_fifo_test(void) {
  alignas(4) uint32_t words[3]  = {0xA1A1A1A1u, 0xB2B2B2B2u, 0xC3C3C3C3u};
  uint8_t             erased[1] = {0};
  pstorage_handle_t   handle    = reset_and_register(0x00026000u);
  dfu_base_address              = handle.block_id;
  dfu_image_page_count          = 1u;
  dfu_page_erased               = erased;

  nested_store_enabled      = true;
  nested_store_handle       = handle;
  nested_store_data         = (uint8_t *)&words[2];
  nested_store_trigger_data = (uint8_t *)&words[0];
  nested_store_size         = 4u;
  nested_store_offset       = 0u;

  if (pstorage_store(&handle, (uint8_t *)&words[0], 4u, 0u) != NRF_SUCCESS ||
      pstorage_store(&handle, (uint8_t *)&words[1], 4u, 0u) != NRF_SUCCESS || erase_calls != 1u) {
    return 160;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (write_calls != 1u || write_values[0] != words[0] || callback_calls != 0u) {
    return 161;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (!nested_store_done || nested_store_result != NRF_SUCCESS || write_calls != 2u || write_values[1] != words[1] ||
      callback_calls != 1u || callback_data[0] != (uint8_t *)&words[0]) {
    return 162;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (write_calls != 3u || write_values[2] != words[2] || callback_calls != 2u ||
      callback_data[1] != (uint8_t *)&words[1]) {
    return 163;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  return callback_calls == 3u && callback_data[2] == (uint8_t *)&words[2] && write_destinations[0] == handle.block_id &&
             write_destinations[1] == handle.block_id && write_destinations[2] == handle.block_id
           ? 0
           : 164;
}

static int pending_final_store_fifo_test(void) {
  alignas(4) uint32_t words[3]  = {0x11110001u, 0x22220002u, 0x33330003u};
  uint8_t             erased[1] = {0};
  pstorage_handle_t   handle    = reset_and_register(0x00026000u);
  dfu_base_address              = handle.block_id;
  dfu_image_page_count          = 1u;
  dfu_page_erased               = erased;

  if (pstorage_store(&handle, (uint8_t *)&words[0], 4u, 0u) != NRF_SUCCESS ||
      pstorage_store(&handle, (uint8_t *)&words[1], 4u, 4u) != NRF_SUCCESS) {
    return 170;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (write_calls != 1u || write_values[0] != words[0] ||
      pstorage_store(&handle, (uint8_t *)&words[2], 4u, 8u) != NRF_SUCCESS) {
    return 171;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (write_calls != 2u || write_values[1] != words[1] || callback_calls != 1u ||
      callback_data[0] != (uint8_t *)&words[0]) {
    return 172;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (write_calls != 3u || write_values[2] != words[2] || callback_calls != 2u ||
      callback_data[1] != (uint8_t *)&words[1]) {
    return 173;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  return callback_calls == 3u && callback_data[2] == (uint8_t *)&words[2] ? 0 : 174;
}

static int pending_clear_backpressure_fifo_test(void) {
  alignas(4) uint32_t word   = 0x44445555u;
  uint8_t             erased = 0;
  pstorage_handle_t   store  = reset_and_register(0x00026000u);
  pstorage_handle_t   clear  = store;
  clear.block_id             = 0x00070000u;
  dfu_base_address           = store.block_id;
  dfu_image_page_count       = 1u;
  dfu_page_erased            = &erased;

  if (pstorage_store(&store, (uint8_t *)&word, sizeof(word), 0u) != NRF_SUCCESS || erase_calls != 1u) {
    return 180;
  }

  /* A later clear must not enter the ordinary queue ahead of the accepted store. */
  if (pstorage_clear(&clear, 4096u) != NRF_ERROR_NO_MEM || erase_calls != 1u || write_calls != 0u) {
    return 181;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (erase_calls != 1u || write_calls != 1u || callback_calls != 0u) {
    return 182;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (callback_calls != 1u || callback_ops[0] != PSTORAGE_STORE_OP_CODE ||
      callback_data[0] != (uint8_t *)&word || callback_results[0] != NRF_SUCCESS) {
    return 183;
  }

  if (pstorage_clear(&clear, 4096u) != NRF_SUCCESS || erase_calls != 2u ||
      erase_pages[1] != clear.block_id / 4096u) {
    return 184;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  return callback_calls == 2u && callback_ops[1] == PSTORAGE_CLEAR_OP_CODE &&
             callback_blocks[1] == clear.block_id && callback_results[1] == NRF_SUCCESS
           ? 0
           : 185;
}

static int pending_abort_reentry_kick_test(void) {
  alignas(4) uint32_t words[4]  = {0x10000001u, 0x20000002u, 0x30000003u, 0x40000004u};
  uint8_t             erased[3] = {0, 0, 0};
  pstorage_handle_t   handle    = reset_and_register(0x00026000u);
  dfu_base_address              = handle.block_id;
  dfu_image_page_count          = 3u;
  dfu_page_erased               = erased;
  erase_results[0]              = NRF_SUCCESS;
  erase_results[1]              = NRF_ERROR_FORBIDDEN;
  erase_result_count            = 2u;

  if (pstorage_store(&handle, (uint8_t *)&words[0], 4u, 0u) != NRF_SUCCESS ||
      pstorage_store(&handle, (uint8_t *)&words[1], 4u, 4096u) != NRF_SUCCESS ||
      pstorage_store(&handle, (uint8_t *)&words[2], 4u, 8192u) != NRF_SUCCESS) {
    return 190;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (write_calls != 1u || callback_calls != 0u) {
    return 191;
  }

  /* Reenter from the first abort callback while a second old packet remains. */
  nested_store_enabled      = true;
  nested_store_handle       = handle;
  nested_store_data         = (uint8_t *)&words[3];
  nested_store_trigger_data = (uint8_t *)&words[1];
  nested_store_size         = 4u;
  nested_store_offset       = 0u;
  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);

  if (!nested_store_done || nested_store_result != NRF_SUCCESS || erase_calls != 2u || write_calls != 2u ||
      callback_calls != 3u || callback_data[0] != (uint8_t *)&words[0] ||
      callback_results[0] != NRF_SUCCESS || callback_data[1] != (uint8_t *)&words[1] ||
      callback_results[1] != NRF_ERROR_FORBIDDEN || callback_data[2] != (uint8_t *)&words[2] ||
      callback_results[2] != NRF_ERROR_FORBIDDEN) {
    return 192;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  if (callback_calls != 4u || callback_data[3] != (uint8_t *)&words[3] ||
      callback_results[3] != NRF_SUCCESS || write_values[1] != words[3]) {
    return 193;
  }

  pstorage_sys_event_handler(NRF_EVT_FLASH_OPERATION_SUCCESS);
  return callback_calls == 4u ? 0 : 194;
}

int main(void) {
  int rc = busy_success_retry_test();
  if (rc == 0) {
    rc = repeated_busy_foreign_error_test();
  }
  if (rc == 0) {
    rc = queued_clear_store_test();
  }
  if (rc == 0) {
    rc = lazy_busy_completion_test();
  }
  if (rc == 0) {
    rc = lazy_queue_full_error_test();
  }
  if (rc == 0) {
    rc = pending_lazy_error_callback_test();
  }
  if (rc == 0) {
    rc = initial_lazy_error_test();
  }
  if (rc == 0) {
    rc = busy_retry_fatal_recovery_test();
  }
  if (rc == 0) {
    rc = owned_event_error_recovery_test();
  }
  if (rc == 0) {
    rc = full_queue_nested_enqueue_test();
  }
  if (rc == 0) {
    rc = nested_enqueue_error_attribution_test();
  }
  if (rc == 0) {
    rc = lazy_erase_identity_test();
  }
  if (rc == 0) {
    rc = pending_store_event_error_test();
  }
  if (rc == 0) {
    rc = pending_store_immediate_error_test();
  }
  if (rc == 0) {
    rc = multi_page_clear_test();
  }
  if (rc == 0) {
    rc = pending_same_address_nested_fifo_test();
  }
  if (rc == 0) {
    rc = pending_final_store_fifo_test();
  }
  if (rc == 0) {
    rc = pending_clear_backpressure_fifo_test();
  }
  if (rc == 0) {
    rc = pending_abort_reentry_kick_test();
  }
  if (rc != 0) {
    fprintf(stderr, "pstorage busy regression failed: %d\n", rc);
    return rc;
  }
  puts("pstorage BUSY retry, rollback, and FIFO tests passed");
  return 0;
}
