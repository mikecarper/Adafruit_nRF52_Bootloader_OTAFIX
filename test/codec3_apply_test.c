// Exercise the real codec-3 entry point using the same simulated NOR flash,
// settings, and committed base/target images as the codec-2 regression suite.
// The Python driver supplies independently encoded DIP1 vectors. No device I/O.
#define main codec2_regression_main
#include "readback_test.c"
#undef main

static unsigned cases, failures;

static void put_u32(uint8_t *p, uint32_t value) {
    p[0] = (uint8_t)value; p[1] = (uint8_t)(value >> 8);
    p[2] = (uint8_t)(value >> 16); p[3] = (uint8_t)(value >> 24);
}

static void select_vector(const uint8_t *vector, size_t size) {
    free(g_mota);
    g_mota = malloc(size + 1u); // one spare byte for the trailing-payload test
    if (!g_mota) exit(2);
    memcpy(g_mota, vector, size);
    g_mota_n = (long)size;
#if defined(MOTA_INTERNAL_BOOTLOADER_UPDATE)
    g_stage_handoff = GPREGRET2_OTA_STAGE_EXPANDED;
    const uint32_t ceiling = MOTA_NRF52_STAGE_CEILING_EXPANDED;
#else
    const uint32_t ceiling = MOTA_NRF52_STAGE_CEILING_LEGACY;
#endif
    g_write_start = (ceiling - (uint32_t)size) & ~(MOTA_NRF52_FLASH_PAGE - 1u);
}

static uint32_t payload_start(void) {
    uint32_t size = rd_u32(g_mota + 23u), block = 1u << g_mota[27u];
    return 205u + 4u * ((size + block - 1u) / block);
}

// outcome: 1 = fully applied; 0 = rejected before invalidating the old app;
//          2 = post-commit verification failure, leaving the bank unbootable.
static void check_apply(const char *name, int outcome) {
    int committed, matches;
    bool applied = run_case(0, &committed, &matches);
    int ok;
    if (outcome == 1) {
        ok = applied && committed && matches && g_settings_writes == 2 &&
             !g_app_write_while_valid && !g_app_write_past_source && g_gpregret2 == 0xB8u;
    } else if (outcome == 0) {
        ok = !applied && g_bank0 == 1 && g_settings_writes == 0 &&
             memcmp(FLASH + MOTA_NRF52_APP_BASE, g_base, g_base_n) == 0;
    } else {
        ok = !applied && !committed && g_bank0 == 0xFF && g_settings_writes == 1 &&
             !g_app_write_while_valid && !g_app_write_past_source;
    }
    cases++;
    if (!ok) {
        fprintf(stderr, "FAIL %s: applied=%d bank=%u matches=%d settings=%d result=%02X\n",
                name, applied, g_bank0, matches, g_settings_writes, g_gpregret2);
        failures++;
    }
}

int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "usage: %s raw.mota compressed.mota mixed.mota\n", argv[0]);
        return 2;
    }
    uint8_t *raw, *packed, *mixed, *legacy;
    long raw_size = load(argv[1], &raw), packed_size = load(argv[2], &packed);
    long mixed_size = load(argv[3], &mixed);
    long legacy_size = load("vectors/delta.mota", &legacy);
    g_base_n = load("vectors/base.img", &g_base);
    g_exp_n = load("vectors/new.img", &g_expect);

    select_vector(legacy, (size_t)legacy_size);
    check_apply("codec-2 backwards compatibility", 1);
#if defined(MOTA_DEFLATE_CODEC)
    const int supports_codec3 = 1;
#else
    const int supports_codec3 = 0;
#endif
    cases++;
    if (!!(g_mota_bl_info.codec_mask & (1u << 3)) != supports_codec3) {
        fprintf(stderr, "FAIL codec-3 capability does not match the compiled decoder\n");
        failures++;
    }
    select_vector(raw, (size_t)raw_size);
    check_apply("two raw records", supports_codec3);
    select_vector(packed, (size_t)packed_size);
    check_apply("two compressed records", supports_codec3);
    select_vector(mixed, (size_t)mixed_size);
    check_apply("raw then compressed record", supports_codec3);

    if (supports_codec3) {
        select_vector(packed, (size_t)packed_size);
        const uint32_t p = payload_start();
        const uint32_t payload_size = rd_u32(g_mota + 23u);
        const uint32_t second = p + 34u + (g_mota[p + 32u] | (g_mota[p + 33u] << 8));
        const unsigned wrapper_fields[] = {0, 4, 5, 6, 7, 12, 16, 20, 24, 28};
        for (unsigned i = 0; i < sizeof(wrapper_fields) / sizeof(wrapper_fields[0]); i++) {
            select_vector(packed, (size_t)packed_size);
            g_mota[p + wrapper_fields[i]] ^= 1u;
            check_apply("bad wrapper magic/version/profile/geometry", 0);
        }
        const uint32_t decoded_sizes[] = {0, 1, 1535, 1537, 0x100001u, UINT32_MAX};
        for (unsigned i = 0; i < sizeof(decoded_sizes) / sizeof(decoded_sizes[0]); i++) {
            select_vector(packed, (size_t)packed_size);
            put_u32(g_mota + p + 8u, decoded_sizes[i]);
            check_apply("bad decoded length", 0);
        }
        const uint16_t record_sizes[] = {0, 1024, 1025, 0x7FFFu, 0xFFFFu};
        for (unsigned i = 0; i < sizeof(record_sizes) / sizeof(record_sizes[0]); i++) {
            select_vector(packed, (size_t)packed_size);
            g_mota[p + 32u] = (uint8_t)record_sizes[i];
            g_mota[p + 33u] = (uint8_t)(record_sizes[i] >> 8);
            check_apply("bad compressed record length/flag", 0);
        }
        select_vector(raw, (size_t)raw_size);
        g_mota[payload_start() + 32u] ^= 1u;
        check_apply("raw record length must equal decoded chunk", 0);
        select_vector(raw, (size_t)raw_size);
        g_mota[payload_start() + 33u] &= 0x7Fu;
        check_apply("raw data cannot masquerade as compressed", 0);
        select_vector(raw, (size_t)raw_size);
        g_mota[payload_start() + 34u] ^= 1u;
        check_apply("wrong decoded detools compression type", 0);

        select_vector(packed, (size_t)packed_size);
        g_mota[p + 34u] |= 4u; // reserved DEFLATE block type
        check_apply("bad first compressed block", 0);
        select_vector(packed, (size_t)packed_size);
        g_mota[second + 2u] |= 4u;
        check_apply("bad final compressed block is caught before app writes", 0);
        select_vector(packed, (size_t)packed_size);
        g_mota[second] = 0; g_mota[second + 1u] = 0;
        check_apply("bad final record length is caught before app writes", 0);

        const uint8_t flags[] = {MFLAG_FULL, MFLAG_BOOTLOADER, 0x80u};
        for (unsigned i = 0; i < sizeof(flags) / sizeof(flags[0]); i++) {
            select_vector(packed, (size_t)packed_size);
            g_mota[9u] |= flags[i];
            check_apply("invalid application manifest flags", 0);
        }
        select_vector(packed, (size_t)packed_size);
        g_mota[8u] = 3;
        check_apply("bootloader format cannot enter application path", 0);
        select_vector(packed, (size_t)packed_size);
        g_mota[97u] ^= 1u;
        check_apply("wrong base hash", 0);
        select_vector(packed, (size_t)packed_size);
        g_mota[32u] ^= 1u;
        check_apply("wrong final image hash keeps bank invalid", 2);

        // Keep the outer container self-consistent so every truncation reaches
        // the decoder preflight instead of merely failing the outer length check.
        // This compressed fixture fits one manifest block, even after appending.
        if (payload_size + 1u >= (1u << packed[27u])) return 2;
        for (uint32_t cut = 1; cut < payload_size; cut++) {
            select_vector(packed, (size_t)packed_size);
            g_mota_n -= cut;
            put_u32(g_mota + 4u, (uint32_t)g_mota_n);
            put_u32(g_mota + 23u, payload_size - cut);
            memcpy(g_mota + g_mota_n - 5, "vk496", 5);
            check_apply("truncated DIP1 payload", 0);
        }
        select_vector(packed, (size_t)packed_size);
        g_mota[g_mota_n - 5] = 0;
        g_mota_n++;
        memcpy(g_mota + g_mota_n - 5, "vk496", 5);
        put_u32(g_mota + 4u, (uint32_t)g_mota_n);
        put_u32(g_mota + 23u, payload_size + 1u);
        check_apply("trailing payload byte", 0);
    }
    free(raw); free(packed); free(mixed); free(legacy);
    free(g_mota); free(g_base); free(g_expect);
    printf("codec-3 %s entrypoint: %u cases, %u failures\n",
           supports_codec3 ? "enabled" : "disabled", cases, failures);
    return failures ? 1 : 0;
}
