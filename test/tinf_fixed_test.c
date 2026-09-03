// Binary batch runner used by tinf_fixed_test.py. A native executable (not a
// library loaded into Python) ensures ASan/UBSan instrument every decode.
#include "tinf/tinf.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#if defined(_WIN32)
#include <fcntl.h>
#include <io.h>
#endif

static uint32_t get_u32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) |
           ((uint32_t)p[3] << 24);
}

int main(void) {
#if defined(_WIN32)
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    uint8_t byte = 0;
    if (tinf_uncompress_fixed(NULL, 1, &byte, 1) == TINF_OK ||
        tinf_uncompress_fixed(&byte, 1, NULL, 1) == TINF_OK) return 2;
    uint8_t header[8];
    size_t got;
    while ((got = fread(header, 1, sizeof(header), stdin)) != 0) {
        if (got != sizeof(header)) return 2;
        uint32_t source_len = get_u32(header), output_len = get_u32(header + 4);
        if (source_len > 4096 || output_len > 2048) return 2;
        // Exact-sized allocations make even a one-byte overread/write visible
        // to the sanitizer. Zero-length API cases still receive non-NULL pointers.
        uint8_t *source = malloc(source_len ? source_len : 1u);
        uint8_t *output = calloc(output_len ? output_len : 1u, 1u);
        if (!source || !output) return 2;
        if (fread(source, 1, source_len, stdin) != source_len) return 2;
        int result = tinf_uncompress_fixed(output, output_len, source, source_len);
        uint32_t code = (uint32_t)result;
        uint8_t reply[4] = {(uint8_t)code, (uint8_t)(code >> 8),
                            (uint8_t)(code >> 16), (uint8_t)(code >> 24)};
        if (fwrite(reply, 1, sizeof(reply), stdout) != sizeof(reply) ||
            fwrite(output, 1, output_len, stdout) != output_len) return 2;
        free(source); free(output);
    }
    return ferror(stdin) || fflush(stdout) ? 2 : 0;
}
