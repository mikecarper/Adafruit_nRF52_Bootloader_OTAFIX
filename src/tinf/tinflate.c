/*
 * tinflate - tiny inflate
 *
 * Copyright (c) 2003-2019 Joergen Ibsen
 *
 * This software is provided 'as-is', without any express or implied
 * warranty. In no event will the authors be held liable for any damages
 * arising from the use of this software.
 *
 * Permission is granted to anyone to use this software for any purpose,
 * including commercial applications, and to alter it and redistribute it
 * freely, subject to the restrictions in LICENSE.
 *
 * OTAFIX alteration: reduced to the codec-3 fixed profile: one raw RFC1951
 * block with BFINAL=1 and BTYPE=1, an exact caller-supplied output size, no
 * trailing bytes, and zero padding bits. Dynamic and stored DEFLATE blocks
 * are deliberately rejected. Based on upstream tinf 1.2.1 commit
 * 57ffa1f1d5e3dde19011b2127bd26d01689b694b.
 */

#include "tinf.h"

#include <limits.h>
#include <stddef.h>
#include <stdint.h>

#if defined(UINT_MAX) && (UINT_MAX) < 0xFFFFFFFFUL
  #error "tinf requires unsigned int to be at least 32-bit"
#endif

struct tinf_data {
  const uint8_t *source;
  const uint8_t *source_end;
  uint32_t       tag;
  unsigned int   bitcount;
  uint8_t       *dest_start;
  uint8_t       *dest;
  uint8_t       *dest_end;
};

static int tinf_getbits(struct tinf_data *d, unsigned int count,
                        unsigned int *value) {
  while (d->bitcount < count) {
    if (d->source == d->source_end) {
      return TINF_DATA_ERROR;
    }
    d->tag |= (uint32_t)*d->source++ << d->bitcount;
    d->bitcount += 8u;
  }
  *value = d->tag & ((1u << count) - 1u);
  d->tag >>= count;
  d->bitcount -= count;
  return TINF_OK;
}

/* Decode the canonical fixed literal/length tree without storing a tree. */
static int tinf_fixed_symbol(struct tinf_data *d, unsigned int *symbol) {
  unsigned int code = 0;
  for (unsigned int len = 1; len <= 9; ++len) {
    unsigned int bit;
    if (tinf_getbits(d, 1, &bit) != TINF_OK) {
      return TINF_DATA_ERROR;
    }
    code = (code << 1) | bit;
    if (len == 7 && code < 24) {
      *symbol = 256u + code;
      return TINF_OK;
    }
    if (len == 8) {
      if (code >= 48 && code < 192) {
        *symbol = code - 48;
        return TINF_OK;
      }
      if (code >= 192 && code < 200) {
        *symbol = 280u + code - 192;
        return TINF_OK;
      }
    }
    if (len == 9 && code >= 400) {
      *symbol = 144u + code - 400;
      return TINF_OK;
    }
  }
  return TINF_DATA_ERROR;
}

static int tinf_fixed_distance(struct tinf_data *d, unsigned int *symbol) {
  unsigned int code = 0;
  for (unsigned int i = 0; i < 5; ++i) {
    unsigned int bit;
    if (tinf_getbits(d, 1, &bit) != TINF_OK) {
      return TINF_DATA_ERROR;
    }
    code = (code << 1) | bit;
  }
  if (code > 29) {
    return TINF_DATA_ERROR;
  }
  *symbol = code;
  return TINF_OK;
}

int tinf_uncompress_fixed(void *dest, unsigned int dest_len,
                          const void *source, unsigned int source_len) {
  if (dest == NULL || source == NULL || dest_len == 0 || source_len == 0) {
    return TINF_DATA_ERROR;
  }

  struct tinf_data d;
  d.source     = (const uint8_t *)source;
  d.source_end = d.source + source_len;
  d.tag        = 0;
  d.bitcount   = 0;
  d.dest_start = (uint8_t *)dest;
  d.dest       = d.dest_start;
  d.dest_end   = d.dest_start + dest_len;

  unsigned int header;
  if (tinf_getbits(&d, 3, &header) != TINF_OK || header != 3u) {
    return TINF_DATA_ERROR; /* exactly BFINAL=1, BTYPE=1 */
  }

  for (;;) {
    unsigned int symbol;
    if (tinf_fixed_symbol(&d, &symbol) != TINF_OK) {
      return TINF_DATA_ERROR;
    }
    if (symbol < 256) {
      if (d.dest == d.dest_end) {
        return TINF_BUF_ERROR;
      }
      *d.dest++ = (uint8_t)symbol;
      continue;
    }
    if (symbol == 256) {
      break;
    }
    if (symbol > 285) {
      return TINF_DATA_ERROR;
    }

    unsigned int index = symbol - 257u;
    unsigned int extra;
    unsigned int length;
    if (index < 8) {
      extra  = 0;
      length = index + 3u;
    } else if (index == 28) {
      extra  = 0;
      length = 258u;
    } else {
      extra = ((index - 8u) >> 2) + 1u;
      length = 3u + (1u << (extra + 2u)) +
               ((index - 8u) & 3u) * (1u << extra);
    }
    if (extra) {
      unsigned int bits;
      if (tinf_getbits(&d, extra, &bits) != TINF_OK) {
        return TINF_DATA_ERROR;
      }
      length += bits;
    }

    unsigned int distance_symbol;
    if (tinf_fixed_distance(&d, &distance_symbol) != TINF_OK) {
      return TINF_DATA_ERROR;
    }
    unsigned int distance_extra;
    unsigned int distance;
    if (distance_symbol < 4) {
      distance_extra = 0;
      distance       = distance_symbol + 1u;
    } else {
      distance_extra = (distance_symbol >> 1) - 1u;
      distance = 1u + (1u << (distance_extra + 1u)) +
                 (distance_symbol & 1u) * (1u << distance_extra);
    }
    if (distance_extra) {
      unsigned int bits;
      if (tinf_getbits(&d, distance_extra, &bits) != TINF_OK) {
        return TINF_DATA_ERROR;
      }
      distance += bits;
    }

    unsigned int produced = (unsigned int)(d.dest - d.dest_start);
    if (distance > produced || length > (unsigned int)(d.dest_end - d.dest)) {
      return TINF_DATA_ERROR;
    }
    while (length--) {
      *d.dest = d.dest[-(int)distance];
      ++d.dest;
    }
  }

  if (d.dest != d.dest_end || d.source != d.source_end || d.tag != 0) {
    return TINF_DATA_ERROR;
  }
  return TINF_OK;
}
