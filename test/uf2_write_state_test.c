#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "uf2_app_flash.h"
#include "uf2_transfer_state.h"

enum {
  TEST_MAX_BLOCKS = 16,
  TEST_APP_KIND = 1,
  TEST_BOOT_KIND = 2,
};

typedef struct {
  uint32_t num_blocks;
  uint32_t num_written;
  uint8_t update_kind;
  bool aborted;
  bool settings_invalidated;
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

static void test_committed_duplicate_aborts(void) {
  TestState state = {0};

  assert(prepare(&state, 3, 1, TEST_APP_KIND) == UF2_TRANSFER_ACCEPT);
  uf2_transfer_commit(1, &state.num_written, state.written_mask);

  // A committed duplicate is indistinguishable from a conflicting block in a
  // second same-size image. It must fail closed before any flash action.
  assert(prepare(&state, 3, 1, TEST_APP_KIND) == UF2_TRANSFER_ABORTED);
  assert(state.aborted);
  assert(state.num_written == 1);
}

static void test_second_same_geometry_image_cannot_complete(void) {
  TestState state = {0};

  // The first image is interrupted after two accepted blocks.
  assert(prepare(&state, 4, 0, TEST_APP_KIND) == UF2_TRANSFER_ACCEPT);
  uf2_transfer_commit(0, &state.num_written, state.written_mask);
  assert(prepare(&state, 4, 1, TEST_APP_KIND) == UF2_TRANSFER_ACCEPT);
  uf2_transfer_commit(1, &state.num_written, state.written_mask);

  // A second image commonly starts again at block zero with identical geometry
  // and kind. The committed block number is an exact, collision-free tripwire.
  assert(prepare(&state, 4, 0, TEST_APP_KIND) == UF2_TRANSFER_ABORTED);
  assert(prepare(&state, 4, 2, TEST_APP_KIND) == UF2_TRANSFER_ABORTED);
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
  state.erased_mask[0] = 0x03;
  assert(prepare(&state, 4, 0, TEST_APP_KIND) == UF2_TRANSFER_ACCEPT);
  uf2_transfer_commit(0, &state.num_written, state.written_mask);
  state.aborted = true;

  uf2_transfer_reset(&state, sizeof(state));
  assert(!state.aborted);
  assert(!state.settings_invalidated);
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

  // The first block is split into three callbacks so settings invalidation,
  // page erase, and programming are separate retryable phases.
  assert(uf2_app_flash_next_action(&settings_invalidated, erased_mask, 0) ==
         UF2_APP_FLASH_INVALIDATE_SETTINGS);
  assert(uf2_app_flash_next_action(&settings_invalidated, erased_mask, 0) ==
         UF2_APP_FLASH_ERASE_PAGE);
  assert(uf2_app_flash_next_action(&settings_invalidated, erased_mask, 0) ==
         UF2_APP_FLASH_PROGRAM_BLOCK);

  // Pages are tracked independently across bitmap-byte boundaries.
  assert(uf2_app_flash_next_action(&settings_invalidated, erased_mask, 9) ==
         UF2_APP_FLASH_ERASE_PAGE);
  assert(uf2_app_flash_next_action(&settings_invalidated, erased_mask, 9) ==
         UF2_APP_FLASH_PROGRAM_BLOCK);
}

int main(void) {
  test_busy_retry_and_completion();
  test_committed_duplicate_aborts();
  test_second_same_geometry_image_cannot_complete();
  test_abort_is_terminal();
  test_explicit_session_reset();
  test_app_flash_phases();
  puts("uf2 write state tests passed");
  return 0;
}
