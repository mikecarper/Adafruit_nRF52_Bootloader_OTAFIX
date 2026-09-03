#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "uf2_app_flash.h"
#include "uf2_current_echo.h"
#include "uf2_transfer_state.h"

enum {
  TEST_MAX_BLOCKS = 16,
  TEST_APP_KIND = 1,
  TEST_BOOT_KIND = 2,
};

typedef struct {
  uint32_t num_blocks;
  uint32_t num_written;
  uint32_t erase_address;
  uint8_t update_kind;
  bool aborted;
  bool settings_invalidated;
  bool erase_in_progress;
  uint8_t written_mask[(TEST_MAX_BLOCKS + 7) / 8];
  uint8_t erased_mask[4];
} TestState;

static uf2_transfer_result_t prepare(TestState* state,
                                     uint32_t num_blocks,
                                     uint32_t block_no,
                                     uint8_t update_kind) {
  return uf2_transfer_prepare(num_blocks, block_no, update_kind, TEST_MAX_BLOCKS,
                              &state->num_blocks, &state->update_kind, &state->aborted,
                              state->written_mask);
}

static void test_busy_retry_and_completion(void) {
  TestState state = {0};

  // A busy flash phase does not commit the block. Retrying it remains accepted.
  assert(prepare(&state, 2, 0, TEST_APP_KIND) == UF2_TRANSFER_ACCEPT);
  assert(prepare(&state, 2, 0, TEST_APP_KIND) == UF2_TRANSFER_ACCEPT);
  assert(state.num_written == 0);

  uf2_transfer_commit(0, &state.num_written, state.written_mask);
  assert(state.num_written == 1);

  assert(prepare(&state, 2, 1, TEST_APP_KIND) == UF2_TRANSFER_ACCEPT);
  uf2_transfer_commit(1, &state.num_written, state.written_mask);
  assert(state.num_written == state.num_blocks);
}

static void test_committed_duplicate_is_reported(void) {
  TestState state = {0};

  assert(prepare(&state, 3, 1, TEST_APP_KIND) == UF2_TRANSFER_ACCEPT);
  uf2_transfer_commit(1, &state.num_written, state.written_mask);

  // The transport layer reports a committed duplicate to the flash-aware
  // caller, which can compare the incoming payload with the destination.
  assert(prepare(&state, 3, 1, TEST_APP_KIND) == UF2_TRANSFER_DUPLICATE);
  assert(!state.aborted);
  assert(state.num_written == 1);

  assert(uf2_transfer_validate_duplicate(UF2_TRANSFER_DUPLICATE, true,
                                         &state.aborted) == UF2_TRANSFER_DUPLICATE);
  assert(!state.aborted);
  assert(uf2_transfer_validate_duplicate(UF2_TRANSFER_DUPLICATE, false,
                                         &state.aborted) == UF2_TRANSFER_ABORTED);
  assert(state.aborted);
}

static void test_duplicate_does_not_advance_completion(void) {
  TestState state = {0};

  // A mass-storage retry is consumed without counting the same block twice.
  assert(prepare(&state, 4, 0, TEST_APP_KIND) == UF2_TRANSFER_ACCEPT);
  uf2_transfer_commit(0, &state.num_written, state.written_mask);
  assert(prepare(&state, 4, 1, TEST_APP_KIND) == UF2_TRANSFER_ACCEPT);
  uf2_transfer_commit(1, &state.num_written, state.written_mask);

  assert(prepare(&state, 4, 0, TEST_APP_KIND) == UF2_TRANSFER_DUPLICATE);
  assert(prepare(&state, 4, 2, TEST_APP_KIND) == UF2_TRANSFER_ACCEPT);
  assert(state.num_written == 2);
  assert(state.num_written < state.num_blocks);
}

static void test_abort_is_terminal(void) {
  TestState state = {0};

  assert(prepare(&state, 2, 0, TEST_APP_KIND) == UF2_TRANSFER_ACCEPT);
  uf2_transfer_commit(0, &state.num_written, state.written_mask);

  // Changing transfer geometry aborts. Every later otherwise-valid block is
  // rejected until a real session reset.
  assert(prepare(&state, 3, 1, TEST_APP_KIND) == UF2_TRANSFER_ABORTED);
  assert(state.aborted);
  assert(prepare(&state, 2, 1, TEST_APP_KIND) == UF2_TRANSFER_ABORTED);
  assert(state.num_written == 1);

  // Changing application/bootloader kind is likewise terminal.
  uf2_transfer_reset(&state, sizeof(state));
  assert(prepare(&state, 2, 0, TEST_APP_KIND) == UF2_TRANSFER_ACCEPT);
  assert(prepare(&state, 2, 1, TEST_BOOT_KIND) == UF2_TRANSFER_ABORTED);
  assert(state.aborted);
}

static void test_explicit_session_reset(void) {
  TestState state = {0};

  state.settings_invalidated = true;
  state.erase_address = 0x26000;
  state.erase_in_progress = true;
  state.erased_mask[0] = 0x03;
  assert(prepare(&state, 4, 0, TEST_APP_KIND) == UF2_TRANSFER_ACCEPT);
  uf2_transfer_commit(0, &state.num_written, state.written_mask);
  state.aborted = true;

  uf2_transfer_reset(&state, sizeof(state));
  assert(!state.aborted);
  assert(!state.settings_invalidated);
  assert(!state.erase_in_progress);
  assert(state.erase_address == 0);
  assert(state.num_blocks == 0);
  assert(state.num_written == 0);
  assert(state.update_kind == 0);
  assert(state.written_mask[0] == 0);
  assert(state.erased_mask[0] == 0);
  assert(prepare(&state, 4, 0, TEST_APP_KIND) == UF2_TRANSFER_ACCEPT);
}

static void test_app_flash_phases(void) {
  bool settings_invalidated = false;
  uint8_t erased_mask[4] = {0};

  // Settings are invalidated before any incoming target page is erased, so an
  // interrupted out-of-order copy cannot leave the old application bootable.
  assert(uf2_app_flash_next_action(&settings_invalidated, erased_mask, 9) ==
         UF2_APP_FLASH_INVALIDATE_SETTINGS);
  assert(erased_mask[0] == 0);
  assert(uf2_app_flash_next_action(&settings_invalidated, erased_mask, 9) ==
         UF2_APP_FLASH_ERASE_PAGE);
  assert(uf2_app_flash_next_action(&settings_invalidated, erased_mask, 9) ==
         UF2_APP_FLASH_PROGRAM_BLOCK);

  // Each additional page is erased exactly once before it is programmed.
  assert(uf2_app_flash_next_action(&settings_invalidated, erased_mask, 0) ==
         UF2_APP_FLASH_ERASE_PAGE);
  assert(uf2_app_flash_next_action(&settings_invalidated, erased_mask, 0) ==
         UF2_APP_FLASH_PROGRAM_BLOCK);
}

static void test_current_uf2_extent_is_read_only(void) {
  enum {
    FIRST_LBA = 523,
    CURRENT_SECTORS = 3728,
  };

  // The decision is based only on physical disk location. The bytes may be a
  // cached CURRENT block, a modified UF2 block, or malformed disk data without
  // changing the result or latching transfer state.
  TestState state = {
      .num_blocks = 7,
      .num_written = 3,
      .update_kind = TEST_APP_KIND,
  };
  assert(uf2_current_lba_is_synthetic(FIRST_LBA, FIRST_LBA,
                                      CURRENT_SECTORS));
  assert(uf2_current_lba_is_synthetic(FIRST_LBA + CURRENT_SECTORS / 2,
                                      FIRST_LBA, CURRENT_SECTORS));
  assert(uf2_current_lba_is_synthetic(FIRST_LBA + CURRENT_SECTORS - 1,
                                      FIRST_LBA, CURRENT_SECTORS));
  assert(state.num_blocks == 7);
  assert(state.num_written == 3);
  assert(state.update_kind == TEST_APP_KIND);
  assert(!state.aborted);

  assert(!uf2_current_lba_is_synthetic(FIRST_LBA - 1, FIRST_LBA,
                                       CURRENT_SECTORS));
  assert(!uf2_current_lba_is_synthetic(FIRST_LBA + CURRENT_SECTORS,
                                       FIRST_LBA, CURRENT_SECTORS));
  assert(!uf2_current_lba_is_synthetic(FIRST_LBA, FIRST_LBA, 0));

  // Subtraction after the lower-bound check avoids an overflowing exclusive
  // end calculation even when the synthetic extent reaches UINT32_MAX.
  assert(uf2_current_lba_is_synthetic(UINT32_MAX, UINT32_MAX - 2, 3));
  assert(!uf2_current_lba_is_synthetic(UINT32_MAX - 3,
                                       UINT32_MAX - 2, 3));
}

static void test_current_tail_crossing_and_saved_copy(void) {
  enum {
    FIRST_LBA = 523,
    CURRENT_SECTORS = 3728,
    WRITE_FIRST_LBA = FIRST_LBA + CURRENT_SECTORS - 3,
  };

  // Pocket/Windows HIL shape: the first three sectors of an eight-sector
  // WRITE10 are the physical CURRENT tail. Every later sector is outside the
  // synthetic file and follows the ordinary non-UF2/UF2 processing path.
  for (uint32_t i = 0; i < 8; ++i) {
    bool const ignored = uf2_current_lba_is_synthetic(
        WRITE_FIRST_LBA + i, FIRST_LBA, CURRENT_SECTORS);
    assert(ignored == (i < 3));
  }

  // A saved CURRENT.UF2 copied back as a new file is allocated beyond the
  // physical extent. Its block zero is therefore accepted as a normal transfer.
  uint32_t const copied_file_lba = FIRST_LBA + CURRENT_SECTORS + 3;
  assert(!uf2_current_lba_is_synthetic(copied_file_lba, FIRST_LBA,
                                       CURRENT_SECTORS));
  TestState state = {0};
  assert(prepare(&state, 8, 0, TEST_APP_KIND) == UF2_TRANSFER_ACCEPT);
  assert(state.num_blocks == 8);
  assert(state.update_kind == TEST_APP_KIND);
  assert(!state.aborted);
}

int main(void) {
  test_busy_retry_and_completion();
  test_committed_duplicate_is_reported();
  test_duplicate_does_not_advance_completion();
  test_abort_is_terminal();
  test_explicit_session_reset();
  test_app_flash_phases();
  test_current_uf2_extent_is_read_only();
  test_current_tail_crossing_and_saved_copy();
  puts("uf2 write state tests passed");
  return 0;
}
