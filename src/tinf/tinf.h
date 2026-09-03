/*
 * tinf - tiny inflate library
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
 * OTAFIX alteration: this header exposes only the bounded, single-block,
 * fixed-Huffman raw-DEFLATE profile used by codec 3. Based on upstream tinf
 * 1.2.1 commit 57ffa1f1d5e3dde19011b2127bd26d01689b694b.
 */

#ifndef TINF_H_INCLUDED
#define TINF_H_INCLUDED

typedef enum {
  TINF_OK         = 0,
  TINF_DATA_ERROR = -3,
  TINF_BUF_ERROR  = -5
} tinf_error_code;

/*
 * Inflate exactly source_len bytes containing one final fixed-Huffman block.
 * Success requires exactly dest_len output bytes, no trailing source bytes,
 * and zero-valued padding bits in the final source byte.
 */
int tinf_uncompress_fixed(void *dest, unsigned int dest_len, const void *source,
                          unsigned int source_len);

#endif /* TINF_H_INCLUDED */
