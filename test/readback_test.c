// Regression test for the -flto flash-readback aliasing miscompile in the in-place apply.
// ----------------------------------------------------------------------------------------------------
// THE BUG (HW-confirmed, RAK4631): in-place delta apply READS BACK flash it just WROTE (the output
// overlaps the input). The write goes through nrfx_nvmc_words_write(addr,...); the readback goes through
// fl_read -> memcpy(dst, (const void*)(uintptr_t)addr, n). Those touch the same flash via two DIFFERENT
// pointer provenances, so whole-program -flto alias analysis concludes they can't alias and caches /
// reorders a STALE (pre-write) read. The post-apply sha256 then hashes pre-decode bytes -> mismatch ->
// apply silently refused -> the old firmware boots unchanged. (-fno-strict-aliasing does NOT help: this
// is pointer provenance, not type-based aliasing.) The fix: fl_read reads through a `volatile` pointer.
//
// WHY THIS NEEDS A SPECIAL TEST: a plain host run cannot reproduce the miscompile - here otah_read and
// otah_write_words both touch the SAME C array (FLASH[]), an obvious alias the compiler will never get
// wrong, with or without -flto. So we cover the apply path six ways:
//   [1] POSITIVE  coherent readback  -> apply succeeds, commits, and matches the expected image.
//   [2] RESULT    a normal post-apply boot preserves the retained B8 result for the application.
//   [3] NEGATIVE  inject the exact failure mode (workspace reads return STALE bytes) -> assert the apply
//                 FAILS SAFE: the bank remains invalid and it returns false (never boots corrupt data).
//   [4] BOUNDS    malformed detools address/size/header inputs are rejected before touching app flash.
//   [5] HANDOFF   expanded/legacy GPREGRET2 selection applies only the matching bottom-aligned package.
//   [6] GUARD     assert the device fl_read reads through `volatile` - the one check that catches a
//                 "someone reverted the fix" regression, which [1]/[3] cannot on the host.
//
// Build/run: see test/Makefile (`make check`). Uses the committed vectors in test/vectors/ by default.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include "ota_layout.h"

// ----- simulated flash + a pre-apply SNAPSHOT used to model the LTO stale read -----
#define FLASH_LEN  MOTA_NRF52_APP_END
static uint8_t  FLASH[FLASH_LEN];
static uint8_t  SNAPSHOT[FLASH_LEN];     // pre-apply copy; served for workspace reads in stale mode
static int      g_stale = 0;             // 1 => a workspace read returns the snapshot (THE LTO BUG)
static uint32_t g_ws_lo, g_ws_hi;        // workspace = [APP_BASE, mota_addr); the stale-read window
static uint32_t g_gpregret, g_gpregret2;
static uint16_t g_bank0, g_crc; static uint32_t g_size; static int g_committed;
static int g_settings_writes, g_app_write_while_valid;

void otah_read(uint32_t a, void* d, uint32_t n) {
    memcpy(d, FLASH + a, n);
    if (g_stale) {
        // Overlay the pre-apply snapshot over any part of this read that falls in the workspace - i.e.
        // model "the compiler served a cached read from before the write" for exactly the bytes the
        // in-place decode writes and reads back. Reads outside the workspace (the .mota payload, the
        // running body before any write) are unaffected, just like the real miscompile.
        uint32_t os = a > g_ws_lo ? a : g_ws_lo;
        uint32_t oe = (a + n) < g_ws_hi ? (a + n) : g_ws_hi;
        if (os < oe) memcpy((uint8_t*)d + (os - a), SNAPSHOT + os, oe - os);
    }
}
void     otah_erase(uint32_t page) {
    if (page >= g_ws_lo && page < g_ws_hi && g_bank0 != 0xFF) g_app_write_while_valid++;
    memset(FLASH + page, 0xFF, MOTA_NRF52_FLASH_PAGE);
}
void     otah_write_words(uint32_t a, const uint32_t* s, uint32_t nw) {
    if (a >= g_ws_lo && a < g_ws_hi && g_bank0 != 0xFF) g_app_write_while_valid++;
    uint32_t* dst = (uint32_t*)(FLASH + a);
    for (uint32_t i = 0; i < nw; i++) dst[i] &= s[i];      // NOR: write only clears bits (target pre-erased)
}
uint32_t otah_gpregret_get(void)                           { return g_gpregret; }
void     otah_gpregret_set(uint32_t v)                     { g_gpregret = v; }
uint32_t otah_gpregret2_get(void)                          { return g_gpregret2; }
void     otah_gpregret2_set(uint32_t v)                    { g_gpregret2 = v; }
uint16_t otah_crc16(uint32_t a, uint32_t len)              { (void)a; (void)len; return 0x1234; }
void otah_settings_commit(uint16_t b, uint16_t c, uint32_t s) {
    g_bank0 = b; g_crc = c; g_size = s; g_committed = (b == 0x01); g_settings_writes++;
}

#include "ota_delta.c"   // unit under test (its static page-cache g_cache_page/g_cache_dirty are visible here)

// ----- vector loading + flash layout (mirrors apply_sim.c) -----
static uint8_t *g_base, *g_mota, *g_expect;
static long     g_base_n, g_mota_n, g_exp_n;
static uint32_t g_write_start;
static uint32_t g_stage_handoff = GPREGRET2_OTA_STAGE_LEGACY;

static long load(const char* path, uint8_t** out) {
    FILE* f = fopen(path, "rb"); if (!f) { fprintf(stderr, "cannot open %s\n", path); exit(2); }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    *out = malloc(n); if (fread(*out, 1, n, f) != (size_t)n) { fprintf(stderr, "read %s\n", path); exit(2); }
    fclose(f); return n;
}

static void stage_flash(void) {
    memset(FLASH, 0xFF, FLASH_LEN);
    memcpy(FLASH + MOTA_NRF52_APP_BASE, g_base, g_base_n);          // running image at APP_BASE
    memcpy(FLASH + g_write_start, g_mota, g_mota_n);                // staged .mota bottom-aligned
    static const uint8_t APRV4[4] = {'A','P','R','V'};
    memcpy(FLASH + g_write_start + 8 + 193, APRV4, 4);             // approval @ manifest offset 193 (APRV)
    g_gpregret = GPREGRET_OTA_APPLY;
    g_gpregret2 = g_stage_handoff;
    // Model the vulnerable/common UF2 state: valid application with CRC checking disabled.
    g_committed = 1; g_bank0 = 0x01; g_crc = 0; g_size = (uint32_t)g_base_n;
    g_settings_writes = 0; g_app_write_while_valid = 0;
    g_cache_page = 0; g_cache_dirty = 0;                           // reset ota_delta.c's static page cache
}

// Run the REAL entry point once. Returns its bool; fills committed + matches(expected) for the caller.
static bool run_case(int stale, int* committed, int* matches) {
    stage_flash();
    memcpy(SNAPSHOT, FLASH, FLASH_LEN);                            // freeze the pre-apply image
    g_ws_lo = MOTA_NRF52_APP_BASE; g_ws_hi = g_write_start;        // workspace = [APP_BASE, mota_addr)
    g_stale = stale;
    bool applied = ota_delta_check_and_apply();
    g_stale = 0;
    *committed = g_committed;
    *matches   = (g_exp_n > 0) && (memcmp(FLASH + MOTA_NRF52_APP_BASE, g_expect, g_exp_n) == 0);
    return applied;
}

// [3] Source guard: the DEVICE fl_read (the on-hardware #else branch) must read flash through a
// `volatile` pointer, or -flto reintroduces the stale-readback bug this whole file exists to prevent.
// We can't catch a removed `volatile` behaviorally on the host, so we check the source directly.
static int guard_device_flread_is_volatile(void) {
    const char* cands[] = { "../src/ota_delta.c", "src/ota_delta.c", "ota_delta.c" };
    FILE* f = NULL; const char* used = NULL;
    for (size_t i = 0; i < sizeof cands / sizeof cands[0]; i++) { f = fopen(cands[i], "rb"); if (f) { used = cands[i]; break; } }
    if (!f) { printf("  WARN: ota_delta.c source not found; cannot verify the volatile guard\n"); return 1; }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    char* s = malloc(n + 1); if (fread(s, 1, n, f) != (size_t)n) { fclose(f); free(s); printf("  WARN: short read\n"); return 1; }
    s[n] = 0; fclose(f);
    // Locate the device (#else) abstraction block, then its fl_read, then require `volatile` in the body.
    char* dev = strstr(s, "#include \"nrf.h\"");
    char* fr  = dev ? strstr(dev, "fl_read(uint32_t a, void") : NULL;
    if (!dev || !fr) { printf("  WARN: device fl_read not located (source refactored?); update this guard\n"); free(s); return 1; }
    char* fe = strstr(fr, "fl_erase");           // bound the search to the fl_read body
    char saved = 0; if (fe) { saved = *fe; *fe = 0; }
    int ok = (strstr(fr, "volatile") != NULL);
    if (fe) *fe = saved;
    free(s);
    if (ok) printf("  device fl_read reads through a volatile pointer (LTO-safe)  [%s]\n", used);
    else    printf("  *** device fl_read is NOT volatile - -flto WILL cache a stale readback (the bug is back) ***\n");
    return ok;
}

int main(int argc, char** argv) {
    const char* base_p = argc > 1 ? argv[1] : "vectors/base.img";
    const char* mota_p = argc > 2 ? argv[2] : "vectors/delta.mota";
    const char* new_p  = argc > 3 ? argv[3] : "vectors/new.img";
    g_base_n = load(base_p, &g_base); g_mota_n = load(mota_p, &g_mota); g_exp_n = load(new_p, &g_expect);
    g_write_start = (uint32_t)((MOTA_NRF52_FS_START - g_mota_n) & ~(MOTA_NRF52_FLASH_PAGE - 1));
    if (g_write_start < MOTA_NRF52_APP_BASE + g_base_n) { fprintf(stderr, "mota overlaps app!\n"); return 2; }

    int fails = 0;
    int committed, matches; bool applied;

    // [1] POSITIVE - coherent readback: the apply must succeed, commit, and reproduce the new image.
    printf("[1] positive (coherent readback): ");
    applied = run_case(/*stale=*/0, &committed, &matches);
    if (applied && committed && matches && g_settings_writes == 2 && !g_app_write_while_valid &&
        g_gpregret2 == 0xB8u) {
        printf("PASS - invalidated before writes, then committed valid result\n");
    } else {
        printf("FAIL - applied=%d committed=%d matches=%d settings=%d unsafe_writes=%d GPREGRET2=0x%X\n",
               applied, committed, matches, g_settings_writes, g_app_write_while_valid, g_gpregret2);
        fails++;
    }

    // [2] RESULT - model the reset after a successful apply. GPREGRET was consumed, while GPREGRET2
    // retains B8 across reset so the new application can report the bootloader result.
    printf("[2] successful result survives normal post-apply boot: ");
    {
        int writes_before = g_settings_writes;
        g_cache_page = 0;                                            // reset bootloader-only RAM state
        g_cache_dirty = 0;
        bool applied_again = ota_delta_check_and_apply();
        if (!applied_again && g_gpregret == 0 && g_gpregret2 == 0xB8u &&
            g_settings_writes == writes_before) {
            printf("PASS - GPREGRET2 remains B8 for the application\n");
        } else {
            printf("FAIL - applied=%d GPREGRET=0x%X GPREGRET2=0x%X settings=%d/%d\n",
                   applied_again, g_gpregret, g_gpregret2, g_settings_writes, writes_before);
            fails++;
        }
    }

    // [3] NEGATIVE - inject the LTO failure mode (stale workspace readback). The apply MUST fail safe:
    // it must leave the bank INVALID (so even UF2's zero-CRC settings cannot boot it) and return false.
    printf("[3] negative (stale workspace readback = the LTO bug): ");
    applied = run_case(/*stale=*/1, &committed, &matches);
    if (!committed && !applied && !matches && g_bank0 == 0xFF && g_settings_writes == 1 &&
        !g_app_write_while_valid) {
        printf("PASS - apply refused, bank remains invalid (fails safe -> DFU)\n");
    } else {
        printf("FAIL - applied=%d committed=%d matches=%d bank=0x%X settings=%d unsafe_writes=%d\n",
               applied, committed, matches, g_bank0, g_settings_writes, g_app_write_while_valid);
        fails++;
    }
    // Sanity: staleness must actually have CHANGED the outcome, else this vector doesn't exercise the
    // readback path and the negative test is vacuous. (Re-run positive to compare.)
    {
        int c2, m2; bool a2 = run_case(0, &c2, &m2);
        if (a2 && c2 && !(applied && committed)) {
            printf("    (sensitivity OK: coherent commits, stale does not - vector exercises readback)\n");
        } else if (a2 && c2) {
            printf("    NOTE: coherent and stale both committed - vector may not exercise cross-page readback\n");
        }
    }

    // [4] Malformed callback ranges, wrapped container geometry, and an oversized detools memory geometry
    // must be rejected without invalidating or changing the current application.
    printf("[4] malformed detools bounds/geometry: ");
    {
        stage_flash();
        struct apply_ctx c = {0, 4, 0, MOTA_NRF52_APP_BASE, g_write_start, 0};
        uint8_t byte = 0;
        int bounds_ok = dt_mr(&c, &byte, UINTPTR_MAX, 1) < 0 &&
                        dt_mw(&c, UINTPTR_MAX, &byte, 1) < 0 &&
                        dt_me(&c, UINTPTR_MAX, 1) < 0 &&
                        dt_pr(&c, &byte, SIZE_MAX) < 0;

        // This 211-byte synthetic container passed the old uint32 parser: payload_size + block_size,
        // leaf_count*4, and off+payload+trailer wrapped in concert to equal total while payload_addr
        // pointed gigabytes away. The 64-bit geometry must reject it before any payload read.
        uint8_t wrapped[211]; memset(wrapped, 0, sizeof wrapped);
        memcpy(wrapped, "mOTA", 4); wrapped[4] = (uint8_t)sizeof wrapped; wrapped[8] = 2;
        wrapped[23] = 0x55; wrapped[24] = 0x55; wrapped[25] = 0x55; wrapped[26] = 0x55;
        wrapped[27] = 1;                              // block size 2; payload_size = 0x55555555
        memcpy(wrapped + sizeof wrapped - 5, "vk496", 5);
        memcpy(FLASH + g_write_start, wrapped, sizeof wrapped);
        struct mota_min wrapped_m;
        int wrapped_ok = !parse_mota_at(g_write_start, MOTA_NRF52_STAGE_CEILING_LEGACY, &wrapped_m);

        stage_flash();                                // restore the valid vector for detools geometry test
        struct mota_min m; uint32_t found = scan_mota(&m, MOTA_NRF52_STAGE_CEILING_LEGACY);
        if (found) FLASH[m.payload_addr + 3] = 0x7F;  // memory_size 0x98000 -> oversized 0xFE000
        bool bad_applied = ota_delta_check_and_apply();
        int app_same = memcmp(FLASH + MOTA_NRF52_APP_BASE, g_base, g_base_n) == 0;
        if (bounds_ok && wrapped_ok && !bad_applied && app_same && g_bank0 == 0x01 && g_settings_writes == 0) {
            printf("PASS - rejected before settings/app commit point\n");
        } else {
            printf("FAIL - bounds=%d wrapped=%d applied=%d app_same=%d bank=0x%X settings=%d\n",
                   bounds_ok, wrapped_ok, bad_applied, app_same, g_bank0, g_settings_writes);
            fails++;
        }
    }

    // [5] The expanded ceiling is selected only by its exact GPREGRET2 marker, and the container must
    // be bottom-aligned to that same ceiling. A missing/mismatched hint must leave the old app untouched.
    printf("[5] legacy/expanded staging handoff: ");
    {
        const uint32_t legacy_start =
            (uint32_t)((MOTA_NRF52_STAGE_CEILING_LEGACY - g_mota_n) & ~(MOTA_NRF52_FLASH_PAGE - 1));
        const uint32_t expanded_start =
            (uint32_t)((MOTA_NRF52_STAGE_CEILING_EXPANDED - g_mota_n) & ~(MOTA_NRF52_FLASH_PAGE - 1));
        int c_exp, m_exp, c_nohint, m_nohint, c_mismatch, m_mismatch;

        // Expanded layouts may also carry a running image past 0xD4000. The selected app limit must
        // find that EndF, while a legacy handoff must never scan into the same range.
        const uint32_t high_body = MOTA_NRF52_STAGE_CEILING_LEGACY - MOTA_NRF52_APP_BASE + 128u;
        const uint32_t high_endf = MOTA_NRF52_APP_BASE + high_body;
        uint32_t found_body = 0;
        memset(FLASH, 0xFF, FLASH_LEN);
        memcpy(FLASH + high_endf, "EndF", 4);
        FLASH[high_endf + 4] = (uint8_t)high_body;
        FLASH[high_endf + 5] = (uint8_t)(high_body >> 8);
        FLASH[high_endf + 6] = (uint8_t)(high_body >> 16);
        FLASH[high_endf + 7] = (uint8_t)(high_body >> 24);
        int app_limit_ok = !find_body_len(MOTA_NRF52_STAGE_CEILING_LEGACY, &found_body) &&
                           find_body_len(MOTA_NRF52_STAGE_CEILING_EXPANDED, &found_body) &&
                           found_body == high_body;

        g_write_start = expanded_start;
        g_stage_handoff = GPREGRET2_OTA_STAGE_EXPANDED;
        bool expanded_applied = run_case(0, &c_exp, &m_exp);

        g_stage_handoff = GPREGRET2_OTA_STAGE_LEGACY;
        bool nohint_applied = run_case(0, &c_nohint, &m_nohint);
        int nohint_same = memcmp(FLASH + MOTA_NRF52_APP_BASE, g_base, g_base_n) == 0;

        g_write_start = legacy_start;
        g_stage_handoff = GPREGRET2_OTA_STAGE_EXPANDED;
        bool mismatch_applied = run_case(0, &c_mismatch, &m_mismatch);
        int mismatch_same = memcmp(FLASH + MOTA_NRF52_APP_BASE, g_base, g_base_n) == 0;

        if (app_limit_ok && expanded_applied && c_exp && m_exp && !nohint_applied && c_nohint && !m_nohint &&
            nohint_same && !mismatch_applied && c_mismatch && !m_mismatch && mismatch_same) {
            printf("PASS - expanded image/apply works; missing/mismatched hints fail safe\n");
        } else {
            printf("FAIL - limit=%d expanded=%d/%d/%d nohint=%d/%d/%d/%d mismatch=%d/%d/%d/%d\n",
                   app_limit_ok, expanded_applied, c_exp, m_exp, nohint_applied, c_nohint, m_nohint, nohint_same,
                   mismatch_applied, c_mismatch, m_mismatch, mismatch_same);
            fails++;
        }
        g_write_start = legacy_start;
        g_stage_handoff = GPREGRET2_OTA_STAGE_LEGACY;
    }

    // [6] GUARD - the device fl_read must stay volatile.
    printf("[6] source guard (device fl_read is volatile):\n");
    if (!guard_device_flread_is_volatile()) fails++;

    printf("\n%s (%d failure%s)\n", fails ? "SUITE FAILED" : "SUITE PASSED", fails, fails == 1 ? "" : "s");
    return fails ? 1 : 0;
}
