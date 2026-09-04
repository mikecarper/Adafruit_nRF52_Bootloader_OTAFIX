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

typedef enum {
  UF2_APPLICATION_TARGET_SKIP,
  UF2_APPLICATION_TARGET_REQUIRE_MATCH,
  UF2_APPLICATION_TARGET_PROGRAM,
  UF2_APPLICATION_TARGET_ABORT,
} uf2_application_target_t;

#define UF2_TRANSFER_BLOCK_SIZE 256U

static inline uf2_application_target_t uf2_application_target_classify(
    uint32_t target_addr, uint32_t user_start, uint32_t app_start,
    uint32_t app_limit) {
  if (target_addr < user_start) {
    return UF2_APPLICATION_TARGET_SKIP;
  }
  if (target_addr < app_start) {
    return UF2_APPLICATION_TARGET_REQUIRE_MATCH;
  }
  if (target_addr < app_limit) {
    return UF2_APPLICATION_TARGET_PROGRAM;
  }
  return UF2_APPLICATION_TARGET_ABORT;
}

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

static inline uf2_transfer_result_t uf2_transfer_target_prepare(
    uint32_t target_addr, uint32_t target_limit, uint8_t* target_mask,
    size_t target_mask_size, bool* aborted) {
  if (*aborted || (target_addr & (UF2_TRANSFER_BLOCK_SIZE - 1U)) != 0 ||
      target_addr >= target_limit) {
    *aborted = true;
    return UF2_TRANSFER_ABORTED;
  }

  uint32_t const target_block = target_addr / UF2_TRANSFER_BLOCK_SIZE;
  uint32_t const pos = target_block / 8U;
  uint8_t const mask = (uint8_t)(1U << (target_block % 8U));
  if (pos >= target_mask_size || (target_mask[pos] & mask) != 0) {
    // A different UF2 block number may not alias an already committed flash
    // destination. Same-block retries are handled before this function.
    *aborted = true;
    return UF2_TRANSFER_ABORTED;
  }
  return UF2_TRANSFER_ACCEPT;
}

static inline void uf2_transfer_target_commit(uint32_t target_addr,
                                              uint8_t* target_mask) {
  uint32_t const target_block = target_addr / UF2_TRANSFER_BLOCK_SIZE;
  target_mask[target_block / 8U] |= (uint8_t)(1U << (target_block % 8U));
}

static inline bool uf2_transfer_target_range_written(uint8_t const* target_mask,
                                                     size_t target_mask_size,
                                                     uint32_t start,
                                                     uint32_t end) {
  if (start >= end || (start & (UF2_TRANSFER_BLOCK_SIZE - 1U)) != 0 ||
      (end & (UF2_TRANSFER_BLOCK_SIZE - 1U)) != 0) {
    return false;
  }
  for (uint32_t address = start; address < end;
       address += UF2_TRANSFER_BLOCK_SIZE) {
    uint32_t const block = address / UF2_TRANSFER_BLOCK_SIZE;
    uint32_t const pos = block / 8U;
    if (pos >= target_mask_size ||
        (target_mask[pos] & (uint8_t)(1U << (block % 8U))) == 0) {
      return false;
    }
  }
  return true;
}

static inline bool uf2_application_finalize(
    uint8_t const* target_mask, size_t target_mask_size, uint32_t app_start,
    uint32_t app_limit, uint32_t maximum_written_end, uint32_t initial_sp,
    uint32_t reset_vector, uint32_t ram_end, uint32_t* app_size) {
  if (app_size == NULL || app_start < UF2_TRANSFER_BLOCK_SIZE ||
      maximum_written_end > app_limit || maximum_written_end <= app_start ||
      !uf2_transfer_target_range_written(target_mask, target_mask_size,
                                         app_start, maximum_written_end)) {
    return false;
  }

  uint32_t const reset_address = reset_vector & ~1UL;
  uint32_t const size = maximum_written_end - app_start;
  if (size < 8U || initial_sp < 0x20000000UL || initial_sp > ram_end ||
      (initial_sp & 7U) != 0 || (reset_vector & 1U) == 0 ||
      reset_address < app_start || reset_address >= maximum_written_end) {
    return false;
  }

  *app_size = size;
  return true;
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
