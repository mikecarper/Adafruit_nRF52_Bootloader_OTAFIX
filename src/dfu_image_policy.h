#ifndef DFU_IMAGE_POLICY_H_
#define DFU_IMAGE_POLICY_H_

#include <stdint.h>

#include "dfu_types.h"

// Validate the unauthenticated START tuple before any size arithmetic or flash
// preparation. Callers provide valid pointers; the selected role must exactly
// match its non-empty components.
uint32_t dfu_start_packet_validate(dfu_start_packet_t const* start_packet,
                                   uint32_t* image_size_out);

// Validate that authenticated/CRC-checked Legacy DFU bytes actually have the
// role and split declared by START. Version order is intentionally not part of
// this policy: compatible signed images may move forward or backward.
uint32_t dfu_image_policy_validate(uint8_t const* image, uint32_t image_len,
                                   dfu_start_packet_t const* start_packet);

#endif
