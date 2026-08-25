#ifndef UF2_TRANSFER_STATE_H_
#define UF2_TRANSFER_STATE_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

typedef enum {
  UF2_TRANSFER_ACCEPT,
  UF2_TRANSFER_DUPLICATE,
  UF2_TRANSFER_ABORTED,
} uf2_transfer_result_t;

static inline uf2_transfer_result_t uf2_transfer_prepare(uint32_t incoming_num_blocks,
                                                         uint32_t block_no,
                                                         uint8_t incoming_kind,
                                                         uint32_t max_blocks,
                                                         uint32_t* num_blocks,
                                                         uint8_t* update_kind,
                                                         bool* aborted,
                                                         uint8_t* written_mask) {
  if (*aborted) {
    return UF2_TRANSFER_ABORTED;
  }

  if (incoming_num_blocks == 0 || incoming_num_blocks > max_blocks ||
      block_no >= incoming_num_blocks) {
    *aborted = true;
    return UF2_TRANSFER_ABORTED;
  }

  if (*num_blocks == 0) {
    *num_blocks = incoming_num_blocks;
  } else if (*num_blocks != incoming_num_blocks) {
    *aborted = true;
    return UF2_TRANSFER_ABORTED;
  }

  if (*update_kind == 0) {
    *update_kind = incoming_kind;
  } else if (*update_kind != incoming_kind) {
    *aborted = true;
    return UF2_TRANSFER_ABORTED;
  }

  uint8_t const mask = 1U << (block_no % 8);
  uint32_t const pos = block_no / 8;
  if (written_mask[pos] & mask) {
    // USB mass-storage hosts may retransmit a completed WRITE10 command. The
    // caller must verify that the committed destination already contains the
    // incoming bytes before accepting this as an idempotent retransmission.
    return UF2_TRANSFER_DUPLICATE;
  }

  return UF2_TRANSFER_ACCEPT;
}

static inline void uf2_transfer_commit(uint32_t block_no,
                                       uint32_t* num_written,
                                       uint8_t* written_mask) {
  uint8_t const mask = 1U << (block_no % 8);
  uint32_t const pos = block_no / 8;
  if (!(written_mask[pos] & mask)) {
    written_mask[pos] |= mask;
    (*num_written)++;
  }
}

static inline uf2_transfer_result_t uf2_transfer_validate_duplicate(
    uf2_transfer_result_t result, bool destination_matches, bool* aborted) {
  if (result == UF2_TRANSFER_DUPLICATE && !destination_matches) {
    *aborted = true;
    return UF2_TRANSFER_ABORTED;
  }

  return result;
}

static inline void uf2_transfer_reset(void* state, size_t state_size) {
  memset(state, 0, state_size);
}

#endif
