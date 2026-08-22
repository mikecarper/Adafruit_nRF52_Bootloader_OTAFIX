#ifndef APP_UTIL_H
#define APP_UTIL_H

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

static inline int is_word_aligned(void const * ptr)
{
    return (((uintptr_t)ptr & 3u) == 0u);
}

#endif
