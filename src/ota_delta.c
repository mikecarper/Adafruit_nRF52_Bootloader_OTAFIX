// MeshCore `.mota` delta-apply for the nRF52 bootloader (single-slot, detools in-place).
// See ota_delta.h for the contract. Compiles for the device (nrfx/SDK) and for a host test harness
// (OTA_DELTA_HOST_TEST: the test TU provides the otah_* flash/settings/gpregret stubs + crc16).
#include "ota_delta.h"
#include "ota_layout.h"
#include "ota_bl_info.h"
#if defined(MOTA_SD_CARD)
#include "ota_sd_handoff.h"
#include "ota_sd_spi.h"
#endif
#include "detools/detools.h"
#include <string.h>
#include <stdint.h>

// Capability marker the running MeshCore app scans for (see ota_bl_info.h). `used` + the reference in
// ota_delta_check_and_apply() keep it through -ffunction/data-sections, --gc-sections and -flto.
__attribute__((used)) const mota_bl_info_t g_mota_bl_info = {
  { MOTA_BL_MAGIC0, MOTA_BL_MAGIC1, MOTA_BL_MAGIC2, MOTA_BL_MAGIC3,
    MOTA_BL_MAGIC4, MOTA_BL_MAGIC5, MOTA_BL_MAGIC6, MOTA_BL_MAGIC7 },
  MOTA_BL_APPLY_ABI,
#if defined(MOTA_SD_CARD)
  (uint16_t)((1u << 0) | (1u << 2)),   // SD: full images and in-place deltas
  { MOTA_BL_STORAGE_SD, 0, 0, 0 },     // raw-SD handoff
#else
  (uint16_t)(1u << 2),                 // internal flash: in-place deltas only
  { MOTA_BL_STORAGE_STAGE_CEILING, 0, 0, 0 }, // GPREGRET2 selects the safe staging ceiling
#endif
};

// ---- `.mota` / EndF on-wire constants (mirror of src/helpers/ota/OtaFormat.h, C-friendly) ---------
static const uint8_t MAGIC[4]    = { 'm','O','T','A' };
static const uint8_t TRAILER[5]  = { 'v','k','4','9','6' };
static const uint8_t ENDF[4]     = { 'E','n','d','F' };
static const uint8_t APRV[4]     = { 'A','P','R','V' };
#define ENDF_LEN          56u    // fixed trailer: marker(4)+body_len(4)+body_hash8(8)+fw_ver(4)+target(4)+hw_id(32)
#define MOTA_MFL          197u   // fixed manifest-minus-leaves length (head 89 + base_hash 8 + signer 32 + sig 64 + approval 4)
#define MFLAG_FULL        0x01u
#define MFLAG_SIGNED      0x02u
#define CODEC_FULL        0u
#define CODEC_INPLACE     2u
#define PAGE              MOTA_NRF52_FLASH_PAGE

// ---- platform flash / settings / gpregret abstraction --------------------------------------------
#ifdef OTA_DELTA_HOST_TEST
  extern void     otah_read(uint32_t addr, void* dst, uint32_t n);
  extern void     otah_erase(uint32_t page_addr);
  extern void     otah_write_words(uint32_t addr, const uint32_t* src, uint32_t nwords);
  extern uint32_t otah_gpregret_get(void);
  extern void     otah_gpregret_set(uint32_t v);
  extern uint32_t otah_gpregret2_get(void);
  extern uint16_t otah_crc16(uint32_t addr, uint32_t len);
  extern void     otah_settings_commit(uint16_t bank0, uint16_t crc, uint32_t size);
  #define APP_BASE        MOTA_NRF52_APP_BASE
  static void     fl_read(uint32_t a, void* d, uint32_t n)            { otah_read(a, d, n); }
  static void     fl_erase(uint32_t page)                            { otah_erase(page); }
  static void     fl_write_words(uint32_t a, const uint32_t* s, uint32_t nw) { otah_write_words(a, s, nw); }
  static uint32_t gpregret_get(void)                                 { return otah_gpregret_get(); }
  static void     gpregret_set(uint32_t v)                           { otah_gpregret_set(v); }
  static uint32_t gpregret2_get(void)                                { return otah_gpregret2_get(); }
  static void     gpregret2_set(uint32_t v)                          { (void)v; }   // diag no-op on host
  static uint16_t crc16_region(uint32_t a, uint32_t len)             { return otah_crc16(a, len); }
#else
  #include "nrf.h"
  #include "nrfx_nvmc.h"
  #include "crc16.h"
  #include "boards.h"
  #include "bootloader_types.h"
  #include "bootloader_settings.h"
  #include "dfu_types.h"
  #define APP_BASE        ((uint32_t)DFU_BANK_0_REGION_START)
  // Read flash through a VOLATILE pointer. In-place apply WRITES flash (nrfx_nvmc_words_write) and then
  // READS IT BACK here (decode readback + the post-apply sha256). Those touch the same flash through two
  // different pointer provenances (an integer-cast read pointer vs the nrfx write), so whole-program -flto
  // alias analysis concludes they can't alias and caches/reorders a STALE read - the post-check then hashes
  // pre-decode bytes -> mismatch -> apply silently refused. (-fno-strict-aliasing does NOT help: this is
  // provenance, not type-based aliasing.) The host harness can't reproduce it: there read+write hit the
  // same C array, an obvious alias. volatile forces the actual load each time.
  static void     fl_read(uint32_t a, void* d, uint32_t n) {
    const volatile uint8_t* s = (const volatile uint8_t*)(uintptr_t)a; uint8_t* o = (uint8_t*)d;
    for (uint32_t i = 0; i < n; i++) o[i] = s[i];
  }
  static void     fl_erase(uint32_t page)                            { nrfx_nvmc_page_erase(page); }
  static void     fl_write_words(uint32_t a, const uint32_t* s, uint32_t nw) { nrfx_nvmc_words_write(a, s, nw); }
  static uint32_t gpregret_get(void)                                 { return NRF_POWER->GPREGRET; }
  static void     gpregret_set(uint32_t v)                           { NRF_POWER->GPREGRET = v; }
  // Diagnostic: stash an apply bail/progress code in GPREGRET2 (retained across the boot to the app, which
  // reads it back). SD is off in the bootloader, so a direct write is fine.
  static uint32_t gpregret2_get(void)                                { return NRF_POWER->GPREGRET2; }
  static void     gpregret2_set(uint32_t v)                          { NRF_POWER->GPREGRET2 = v; }
  static uint16_t crc16_region(uint32_t a, uint32_t len)             { return crc16_compute((const uint8_t*)(uintptr_t)a, len, NULL); }
  static void otah_settings_commit(uint16_t bank0, uint16_t crc, uint32_t size) {
    bootloader_settings_t s; const bootloader_settings_t* cur;
    bootloader_util_settings_get(&cur); memcpy(&s, cur, sizeof(s));
    s.bank_0 = bank0; s.bank_0_crc = crc; s.bank_0_size = size;
    nrfx_nvmc_page_erase(BOOTLOADER_SETTINGS_ADDRESS);
    nrfx_nvmc_words_write(BOOTLOADER_SETTINGS_ADDRESS, (const uint32_t*)&s, sizeof(s) / 4);
  }
  #define BANK_VALID_APP_V  0x01u
  #define BANK_INVALID_APP_V 0xFFu
#endif
#ifdef OTA_DELTA_HOST_TEST
  #define BANK_VALID_APP_V  0x01u
  #define BANK_INVALID_APP_V 0xFFu
#endif

#include "sha256.h"

// The application watchdog survives the NVIC reset used to enter this
// bootloader. Normal BLE/USB DFU reloads it from bootloader.c's event loop,
// while the in-place delta applier runs outside that loop. Keep every enabled
// reload channel alive throughout the potentially long scan/hash/apply path.
// A host test has no hardware watchdog, so this becomes a no-op there.
static void inherited_watchdog_feed(void) {
#ifndef OTA_DELTA_HOST_TEST
  static uint8_t external_feed_divider;

  if (NRF_WDT->RUNSTATUS != 0) {
    const uint32_t enabled_channels = NRF_WDT->RREN & 0xFFu;
    for (uint8_t channel = 0; channel < 8; channel++) {
      if ((enabled_channels & (1u << channel)) != 0) {
        NRF_WDT->RR[channel] = WDT_RR_RR_Reload;
      }
    }
  }

  // The external watchdog pulse is deliberately less frequent than the cheap
  // internal reload. Hashing calls this checkpoint every 256 bytes; pulsing on
  // every call would add several seconds to a large update.
  if ((external_feed_divider++ & 0x7FU) == 0) {
    board_watchdog_feed();
  }
#endif
}

static uint32_t rd_u32(const uint8_t* p) {
  return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

#if defined(MOTA_SD_CARD)
static uint32_t g_sd_first_sector;
static uint32_t g_sd_total_size;

// In an SD build, patch/container offsets are relative to the first sector
// named by the handoff. Internal-flash builds continue to use absolute flash
// addresses, preserving the existing tested path.
static int staged_read(uint32_t address_or_offset, void* dst, uint32_t len) {
  if ((uint64_t)address_or_offset + len > g_sd_total_size) return 0;
  return ota_sd_read_bytes(g_sd_first_sector, address_or_offset, dst, len) ? 1 : 0;
}
#else
static int staged_read(uint32_t address_or_offset, void* dst, uint32_t len) {
  fl_read(address_or_offset, dst, len);
  return 1;
}
#endif

// Tiny bounds-checked cursor so the manifest is parsed by reading each field by name in order, instead of
// hand-computed offsets (mirrors MeshCore's OtaByteIO.h ByteReader). Any over-read flips ok=0.
typedef struct { const uint8_t* p; uint32_t len, n; int ok; } br_t;
static uint8_t  br_u8(br_t* r)  { if (r->ok && (uint64_t)r->n + 1 <= r->len) return r->p[r->n++]; r->ok = 0; return 0; }
static uint32_t br_u32(br_t* r) { if (r->ok && (uint64_t)r->n + 4 <= r->len) { uint32_t v = rd_u32(r->p + r->n); r->n += 4; return v; } r->ok = 0; return 0; }
static const uint8_t* br_take(br_t* r, uint32_t k) { if (r->ok && (uint64_t)r->n + k <= r->len) { const uint8_t* x = r->p + r->n; r->n += k; return x; } r->ok = 0; return NULL; }
static void br_skip(br_t* r, uint32_t k) { if (r->ok && (uint64_t)r->n + k <= r->len) r->n += k; else r->ok = 0; }

static void sha256_region(uint32_t addr, uint32_t len, uint8_t out[32]) {
  sha256_ctx_t c; sha256_init(&c);
  uint8_t buf[256];
  while (len) {
    inherited_watchdog_feed();
    uint32_t n = len < sizeof(buf) ? len : sizeof(buf);
    fl_read(addr, buf, n); sha256_update(&c, buf, n); addr += n; len -= n;
  }
  sha256_final(&c, out);
}

// ---- coherent single-page write-back cache (in-place reads back shifted data it just wrote) -------
static uint8_t  g_cache[PAGE] __attribute__((aligned(4)));
static uint32_t g_cache_page;                   // page-aligned addr; 0 == INVALID (no app page is at 0)
static int      g_cache_dirty;

static void cache_flush(void) {
  if (!g_cache_page) return;
  if (g_cache_dirty) {
    inherited_watchdog_feed();
    fl_erase(g_cache_page);
    inherited_watchdog_feed();
    fl_write_words(g_cache_page, (const uint32_t*)g_cache, PAGE / 4);
  }
  g_cache_page = 0; g_cache_dirty = 0;
}
static void cache_use(uint32_t page) {
  if (g_cache_page == page) return;
  cache_flush();
  g_cache_page = page; g_cache_dirty = 0;
  fl_read(page, g_cache, PAGE);
}
static void cread(uint32_t addr, uint8_t* dst, uint32_t n) {     // coherent read (overlay dirty page)
  fl_read(addr, dst, n);
  if (g_cache_page && g_cache_dirty) {
    uint32_t cs = g_cache_page, ce = g_cache_page + PAGE, a = addr, e = addr + n;
    uint32_t os = a > cs ? a : cs, oe = e < ce ? e : ce;
    if (os < oe) memcpy(dst + (os - a), g_cache + (os - cs), oe - os);
  }
}
static void cwrite(uint32_t addr, const uint8_t* src, uint32_t n) {
  while (n) {
    uint32_t page = addr & ~(PAGE - 1), off = addr - page, chunk = PAGE - off;
    if (chunk > n) chunk = n;
    cache_use(page); memcpy(g_cache + off, src, chunk); g_cache_dirty = 1;
    addr += chunk; src += chunk; n -= chunk;
  }
}
static void cerase(uint32_t addr, uint32_t n) {                  // detools calls this page-aligned
  while (n) {
    uint32_t page = addr & ~(PAGE - 1), off = addr - page, step = PAGE - off;
    if (step > n) step = n;
    if (g_cache_page == page) { memset(g_cache, 0xFF, PAGE); g_cache_dirty = 1; }
    else fl_erase(page);
    addr += step; n -= step;
  }
}

// ---- detools in-place callbacks (region addresses are 0-based; base sits at workspace offset 0) ---
struct apply_ctx {
  uint32_t patch_addr, patch_len, patch_pos;
  uint32_t ws_lo, ws_hi;        // workspace = [ws_lo, ws_hi); ws_hi == mota start (never written)
  int step;
};
static int dt_ws_addr(const struct apply_ctx* c, uintptr_t off, size_t n, uint32_t* addr) {
  uint32_t span = c->ws_hi - c->ws_lo;
  if (off > UINT32_MAX || n > UINT32_MAX) return 0;
  uint32_t o = (uint32_t)off, z = (uint32_t)n;
  if (o > span || z > span - o) return 0;
  *addr = c->ws_lo + o;
  return 1;
}
static int dt_mr(void* a, void* dst, uintptr_t src, size_t n) {
  struct apply_ctx* c = a; uint32_t addr;
  if (!dt_ws_addr(c, src, n, &addr)) return -DETOOLS_IO_FAILED;
  inherited_watchdog_feed();
  cread(addr, dst, n); return DETOOLS_OK;
}
static int dt_mw(void* a, uintptr_t dst, void* src, size_t n) {
  struct apply_ctx* c = a; uint32_t addr;
  if (!dt_ws_addr(c, dst, n, &addr)) return -DETOOLS_IO_FAILED;
  inherited_watchdog_feed();
  cwrite(addr, (const uint8_t*)src, n); return DETOOLS_OK;
}
static int dt_me(void* a, uintptr_t addr0, size_t n) {
  struct apply_ctx* c = a; uint32_t addr;
  if (!dt_ws_addr(c, addr0, n, &addr)) return -DETOOLS_IO_FAILED;
  inherited_watchdog_feed();
  cerase(addr, n); return DETOOLS_OK;
}
static int dt_ss(void* a, int s) { ((struct apply_ctx*)a)->step = s; return DETOOLS_OK; }
static int dt_sg(void* a, int* s) { *s = ((struct apply_ctx*)a)->step; return DETOOLS_OK; }
static int dt_pr(void* a, uint8_t* dst, size_t n) {
  struct apply_ctx* c = a;
  if (n > UINT32_MAX || c->patch_pos > c->patch_len || (uint32_t)n > c->patch_len - c->patch_pos)
    return -DETOOLS_IO_FAILED;
  inherited_watchdog_feed();
  if (!staged_read(c->patch_addr + c->patch_pos, dst, (uint32_t)n)) return -DETOOLS_IO_FAILED;
  c->patch_pos += (uint32_t)n; return DETOOLS_OK;
}

// Decode the five unsigned sizes in an in-place detools header without starting the decoder. This lets
// us reject impossible flash geometry while the running application and its boot settings are intact.
static int dt_header_u32(uint32_t addr, uint32_t len, uint32_t* pos, uint32_t* out) {
  uint8_t b;
  if (*pos >= len) return 0;
  if (!staged_read(addr + (*pos)++, &b, 1)) return 0;
  uint32_t v = b & 0x3Fu;
  uint32_t shift = 6;
  while (b & 0x80u) {
    if (*pos >= len) return 0;
    if (!staged_read(addr + (*pos)++, &b, 1)) return 0;
    uint32_t bits = b & 0x7Fu;
    if (shift >= 32 || bits > (UINT32_MAX >> shift)) return 0;
    v |= bits << shift;
    shift += 7;
  }
  if (v > 0x7FFFFFFFu) return 0;                  // detools stores header sizes in signed int
  *out = v;
  return 1;
}

// ---- `.mota` parse (fixed fields only) + EndF base location --------------------------------------
struct mota_min {
  uint32_t total, image_size, payload_size, payload_addr, approval_addr;
  uint8_t  base_hash[8], image_hash[32], codec_id, is_full, approved;
};
static int dt_geometry_ok(const struct mota_min* m, uint32_t body_len, uint32_t ws_span) {
  uint8_t fixed;
  uint32_t p = 1, memory, segment, shift, from, to;
  if (m->payload_size < 2) return 0;
  if (!staged_read(m->payload_addr, &fixed, 1)) return 0;
  if (((fixed >> 4) & 0x07u) != 1u) return 0;      // detools PATCH_TYPE_IN_PLACE
  if (!dt_header_u32(m->payload_addr, m->payload_size, &p, &memory) ||
      !dt_header_u32(m->payload_addr, m->payload_size, &p, &segment) ||
      !dt_header_u32(m->payload_addr, m->payload_size, &p, &shift) ||
      !dt_header_u32(m->payload_addr, m->payload_size, &p, &from) ||
      !dt_header_u32(m->payload_addr, m->payload_size, &p, &to)) return 0;
  if (memory == 0 || memory > ws_span || segment != PAGE || shift > memory ||
      shift % segment != 0 || from > memory - shift || to > memory) return 0;
  if (body_len > UINT32_MAX - ENDF_LEN || from != body_len + ENDF_LEN) return 0;
  return to == m->image_size && to <= ws_span;
}
static int parse_mota_at(uint32_t addr, uint32_t limit, struct mota_min* o) {
  uint8_t b[8 + MOTA_MFL];                          // MAGIC+total + the whole fixed manifest-minus-leaves
  if (addr > limit) return 0;
  uint32_t avail = limit - addr;
  uint32_t hdr = avail < sizeof(b) ? avail : sizeof(b);
  if (hdr < 8 + MOTA_MFL) return 0;                 // need the whole fixed manifest in `b` (trailer read separately)
  if (!staged_read(addr, b, hdr)) return 0;
  if (memcmp(b, MAGIC, 4) != 0) return 0;
  uint32_t total = rd_u32(b + 4);
  if (total < 8 + MOTA_MFL + 5 || total > avail) return 0;
  uint8_t tr[5]; if (!staged_read(addr + total - 5, tr, 5)) return 0;
  if (memcmp(tr, TRAILER, 5) != 0) return 0;

  // Fixed-layout manifest - every field at a constant offset; base_hash/signer/signature are always
  // present (zero-filled when not applicable), so there are no conditionals (docs/ota_protocol.md Section 4).
  br_t r = { b, hdr, 0, 1 };
  br_skip(&r, 4 + 4);                               // MAGIC + MOTA_TOTAL_SIZE (already validated above)
  if (br_u8(&r) != 2) return 0;                     // format_ver
  uint8_t flags  = br_u8(&r);
  br_u8(&r);                                        // hash_algo
  br_skip(&r, 4 + 4);                               // target_id, fw_version (unused here)
  o->image_size   = br_u32(&r);
  o->payload_size = br_u32(&r);
  uint8_t bsl     = br_u8(&r);
  br_skip(&r, 4);                                   // merkle_root
  const uint8_t* ih = br_take(&r, 32); if (ih) memcpy(o->image_hash, ih, 32);
  o->codec_id     = br_u8(&r);
  br_skip(&r, 32);                                  // hw_id (unused here)
  o->is_full      = (flags & MFLAG_FULL) ? 1 : 0;
  const uint8_t* bh = br_take(&r, 8); if (bh) memcpy(o->base_hash, bh, 8);   // base_hash (zero for full)
  br_skip(&r, 32 + 64);                             // signer pubkey + signature (zero when unsigned)
  if (!r.ok) return 0;
  o->approval_addr = addr + r.n;
  const uint8_t* ap = br_take(&r, 4);
  o->approved = (ap && memcmp(ap, APRV, 4) == 0) ? 1 : 0;
  if (bsl == 0 || bsl > 24 || o->payload_size == 0) return 0;
  // Do all variable-length geometry in 64 bits. With corrupt 32-bit sizes, the old ceil-divide,
  // leaf-count multiplication, and final sum could wrap together into a small self-consistent `total`,
  // leaving payload_addr far outside the staged container.
  uint64_t bs = 1ull << bsl;
  uint64_t bc = ((uint64_t)o->payload_size + bs - 1) / bs;
  uint64_t off = (uint64_t)r.n + bc * 4u;            // leaves[] then payload
  if (off + o->payload_size + 5u != total) return 0; // payload must end exactly at the trailer
  o->payload_addr = addr + (uint32_t)off;            // exact-total check proves off < total <= avail
  o->total = total;
  return 1;
}

// Scan page boundaries for a valid `.mota`, returning the HIGHEST one below the selected ceiling.
//
// Direction matters for safety. The app stages the container bottom-aligned and writes [write_start,
// stage_ceiling) contiguously (0xFF-padding the tail), so the *current* `.mota` is always the
// highest in flash; a leftover from a prior, differently-sized fetch sits strictly BELOW it (a larger
// new fetch overwrites everything from its lower start up to the ceiling). Scanning top-down therefore
// returns the current container and never stops on a stale one - and the caller's APRV check is applied
// to THAT (highest) container only, so a stale lower `.mota` is never applied even if it is still
// approved. Exact bottom-alignment also prevents a mismatched ceiling hint from selecting a package.
// (EndF is the mirror image: the app image grows up from APP_BASE, so the current trailer is
// the LOWEST valid marker and find_body_len scans bottom-up. Each marker is scanned from the end where
// the current one is encountered first.)
#define MOTA_MIN_LEN  (8 + MOTA_MFL + 5)
static uint32_t scan_mota(struct mota_min* o, uint32_t stage_ceiling) {
#if defined(MOTA_SD_CARD)
  (void)stage_ceiling;
  uint8_t handoff[MOTA_SD_SECTOR_SIZE];
  if (!ota_sd_init() || !ota_sd_read_sector(MOTA_SD_HANDOFF_SECTOR, handoff)) return 0;
  if (memcmp(handoff, MOTA_SD_HANDOFF_MAGIC, 8) != 0 ||
      mota_sd_handoff_rd32(handoff + 8) != MOTA_SD_HANDOFF_VERSION ||
      mota_sd_handoff_crc32(handoff, 32) != mota_sd_handoff_rd32(handoff + 32)) return 0;
  uint32_t first = mota_sd_handoff_rd32(handoff + 12);
  uint32_t sectors = mota_sd_handoff_rd32(handoff + 16);
  uint32_t total = mota_sd_handoff_rd32(handoff + 20);
  uint32_t total_inv = mota_sd_handoff_rd32(handoff + 24);
  uint32_t card_sectors = mota_sd_handoff_rd32(handoff + 28);
  if (first <= MOTA_SD_HANDOFF_SECTOR || sectors == 0 || total < MOTA_MIN_LEN ||
      total_inv != ~total || (uint64_t)sectors * MOTA_SD_SECTOR_SIZE < total ||
      first >= card_sectors || sectors > card_sectors - first) return 0;
  g_sd_first_sector = first;
  g_sd_total_size = total;
  if (!parse_mota_at(0, g_sd_total_size, o) || o->total != total) return 0;
  return 1;                                           // nonzero sentinel; container begins at file offset 0
#else
  if (stage_ceiling != MOTA_NRF52_STAGE_CEILING_LEGACY &&
      stage_ceiling != MOTA_NRF52_STAGE_CEILING_EXPANDED) return 0;
  uint32_t top = (stage_ceiling - MOTA_MIN_LEN) & ~(PAGE - 1);
  for (uint32_t a = top + PAGE; a > APP_BASE; ) {        // walk page boundaries high -> low
    a -= PAGE;
    inherited_watchdog_feed();
    uint8_t m4[4]; fl_read(a, m4, 4);
    if (memcmp(m4, MAGIC, 4) == 0 && parse_mota_at(a, stage_ceiling, o) &&
        ((stage_ceiling - o->total) & ~(PAGE - 1u)) == a) return a;
  }
  return 0;
#endif
}

// Locate the running image's EndF trailer (= body_len) by scanning bottom-up for the self-validating
// marker (mirrors the app's FirmwareInfo::find_self_firmware). We deliberately do NOT trust
// bootloader_settings.bank_0_size: the UF2 flasher does not set it to the exact EndF-inclusive image
// size, so trusting it makes a freshly UF2-flashed app fail the base check and silently refuse its first
// OTA update. Bottom-up returns the CURRENT (lowest) trailer; a stale one from a prior larger image sits
// above it and is never reached. No hash check is needed here: the caller immediately recomputes
// sha256(body) and compares it to the delta's base_hash, so a (vanishingly unlikely) coincidental "EndF"
// just fails that gate and the update is refused - never misapplied. Byte-by-byte (like the app) so no
// body_len alignment is assumed; the scan stops at the first match (the current image's trailer).
static int find_body_len(uint32_t app_limit, uint32_t* body_len_out) {
  if (app_limit <= APP_BASE) return 0;
  for (uint32_t off = 0; off + ENDF_LEN <= app_limit - APP_BASE; off++) {
    if ((off & (PAGE - 1u)) == 0) inherited_watchdog_feed();
    uint8_t e[8];
    fl_read(APP_BASE + off, e, 8);                  // marker(4) + body_len(4)
    if (memcmp(e, ENDF, 4) == 0 && rd_u32(e + 4) == off) { *body_len_out = off; return 1; }
  }
  return 0;
}

static void clear_approval(const struct mota_min* o) {
#if defined(MOTA_SD_CARD)
  // The trigger was already consumed from GPREGRET. The app invalidates sector
  // 1 before staging another update, so the SD file cannot be retried by a
  // normal reset and no raw-sector write implementation is needed here.
  (void)o;
#else
  uint8_t z[4] = { 0, 0, 0, 0 };
  cwrite(o->approval_addr, z, 4);
  cache_flush();
#endif
}

#if defined(MOTA_SD_CARD)
static int sha256_staged_region(uint32_t offset, uint32_t len, uint8_t out[32]) {
  sha256_ctx_t c; sha256_init(&c);
  uint8_t buf[256];
  while (len) {
    inherited_watchdog_feed();
    uint32_t n = len < sizeof(buf) ? len : sizeof(buf);
    if (!staged_read(offset, buf, n)) return 0;
    sha256_update(&c, buf, n);
    offset += n;
    len -= n;
  }
  sha256_final(&c, out);
  return 1;
}

static bool apply_full_sd(const struct mota_min* m) {
  if (!m->is_full || m->codec_id != CODEC_FULL ||
      m->image_size == 0 || m->payload_size != m->image_size ||
      m->image_size > MOTA_NRF52_APP_END - APP_BASE) {
    gpregret2_set(0xB3);
    return false;
  }

  // Verify the complete SD payload before the first destructive flash write.
  uint8_t h[32];
  if (!sha256_staged_region(m->payload_addr, m->payload_size, h) ||
      memcmp(h, m->image_hash, sizeof(h)) != 0) {
    gpregret2_set(0xBA);
    return false;
  }

  inherited_watchdog_feed();
  otah_settings_commit(BANK_INVALID_APP_V, 0, 0);
  clear_approval(m);
  g_cache_page = 0;
  g_cache_dirty = 0;

  for (uint32_t off = 0; off < m->image_size; off += PAGE) {
    inherited_watchdog_feed();
    uint32_t n = m->image_size - off;
    if (n > PAGE) n = PAGE;
    memset(g_cache, 0xFF, PAGE);
    if (!staged_read(m->payload_addr + off, g_cache, n)) {
      gpregret2_set(0xBB);
      return false;
    }
    fl_erase(APP_BASE + off);
    inherited_watchdog_feed();
    fl_write_words(APP_BASE + off, (const uint32_t*)g_cache, PAGE / 4);
  }

  sha256_region(APP_BASE, m->image_size, h);
  if (memcmp(h, m->image_hash, sizeof(h)) != 0) {
    gpregret2_set(0xB7);
    return false;
  }
  inherited_watchdog_feed();
  uint16_t image_crc = crc16_region(APP_BASE, m->image_size);
  inherited_watchdog_feed();
  otah_settings_commit(BANK_VALID_APP_V, image_crc, m->image_size);
  gpregret2_set(0xB8);
  return true;
}
#endif

static bool finish_apply(bool result) {
#if defined(MOTA_SD_CARD)
  // A rejected handoff falls through to the application without a hardware
  // reset, so do not leave SPIM2 or the SD pins owned by the bootloader.
  ota_sd_deinit();
#endif
  return result;
}

bool ota_delta_check_and_apply(void) {
  inherited_watchdog_feed();
  // Force a volatile read of the capability marker so -flto / --gc-sections cannot fold the reference away
  // and drop it - the running app scans the bootloader flash for it (ota_bl_info.h / OtaBlInfo.h).
  volatile uint8_t keep = *(const volatile uint8_t*)&g_mota_bl_info.magic[0];
  if (keep == 0) return finish_apply(false);        // 'M' (0x4D) != 0, so never taken; keeps the marker live
  // Read the app's staging-window handoff BEFORE GPREGRET2 becomes our diagnostic result register.
  // Backward compatibility is deliberately one-way safe: an old app leaves no recognized expanded
  // marker, so this bootloader scans only below ExtraFS. A new app uses EXPANDED only after finding the
  // matching capability bit in g_mota_bl_info.
  const uint32_t stage_handoff = gpregret2_get();
  const uint32_t stage_ceiling = stage_handoff == GPREGRET2_OTA_STAGE_EXPANDED
      ? MOTA_NRF52_STAGE_CEILING_EXPANDED : MOTA_NRF52_STAGE_CEILING_LEGACY;
#if defined(MOTA_SD_CARD)
  const uint32_t app_limit = MOTA_NRF52_APP_END;
#else
  const uint32_t app_limit = stage_ceiling;
#endif
  // ---- DIAGNOSTIC: stash a bail/progress code in GPREGRET2; the app reads it back into `ota status`.
  // 0xB0 entered (pre-gate) | 0xB1 gate passed (GPREGRET was 0x6A) | 0xB2 no/unapproved mota |
  // 0xB3 bad full/codec | 0xB4 no body_len | 0xB5 base mismatch | 0xB9 bad detools geometry |
  // 0xBA SD full pre-hash mismatch | 0xBB SD read failure |
  // 0x9N detools err N | 0xB6 wrong size | 0xB7 result-hash mismatch | 0xB8 SUCCESS.
  // If status shows 0xB0 -> GPREGRET wasn't 0x6A at the bootloader.
  gpregret2_set(0xB0);
  if (gpregret_get() != GPREGRET_OTA_APPLY) return finish_apply(false);
  gpregret_set(0);                                  // consume the trigger so we never loop
  gpregret2_set(0xB1);

  struct mota_min m;
  uint32_t mota_addr = scan_mota(&m, stage_ceiling);
  if (!mota_addr || !m.approved) { gpregret2_set(0xB2); return finish_apply(false); } // nothing staged / unapproved

#if defined(MOTA_SD_CARD)
  if (m.is_full) return finish_apply(apply_full_sd(&m));
#endif

  // base check (non-destructive): the running image's body must hash to the delta's base_hash.
  // Any pre-apply rejection clears the approval (this `.mota` is not applicable) and boots normally.
  uint32_t body_len;
  uint8_t base32[32];
  if (m.is_full || m.codec_id != CODEC_INPLACE ||
      m.image_size == 0 || m.image_size > app_limit - APP_BASE) {
    gpregret2_set(0xB3); goto reject;
  }
  if (!find_body_len(app_limit, &body_len))     { gpregret2_set(0xB4); goto reject; }
  sha256_region(APP_BASE, body_len, base32);
  if (memcmp(base32, m.base_hash, 8) != 0)      { gpregret2_set(0xB5); goto reject; }   // wrong base
#if defined(MOTA_SD_CARD)
  const uint32_t workspace_span = app_limit - APP_BASE;
#else
  const uint32_t workspace_span = mota_addr - APP_BASE;
#endif
  if (!dt_geometry_ok(&m, body_len, workspace_span)) {
    gpregret2_set(0xB9); goto reject;
  }

  // Commit point: make every subsequent reset enter DFU BEFORE the first destructive application write.
  // This is essential for UF2-installed apps, whose zero CRC otherwise makes a partial image bootable.
  inherited_watchdog_feed();
  otah_settings_commit(BANK_INVALID_APP_V, 0, 0);

  // Consume approval before applying so a failed patch is never retried automatically.
  clear_approval(&m);

  struct apply_ctx c;
  c.patch_addr = m.payload_addr; c.patch_len = m.payload_size; c.patch_pos = 0;
  c.ws_lo = APP_BASE;
#if defined(MOTA_SD_CARD)
  c.ws_hi = app_limit;                                  // patch is off-chip; whole app region is workspace
#else
  c.ws_hi = mota_addr;                                  // workspace stays strictly below internal mota
#endif
  c.step = 0;
  int r = detools_apply_patch_in_place_callbacks(dt_mr, dt_mw, dt_me, dt_ss, dt_sg, dt_pr,
                                                 (size_t)m.payload_size, &c);
  cache_flush();
  if (r < 0) { gpregret2_set(0x90 | ((uint32_t)(-r) & 0x0F)); return finish_apply(false); }
  if ((uint32_t)r != m.image_size) { gpregret2_set(0xB6); return finish_apply(false); }

  uint8_t h[32];
  sha256_region(APP_BASE, m.image_size, h);
  if (memcmp(h, m.image_hash, 32) != 0) { gpregret2_set(0xB7); return finish_apply(false); }

  inherited_watchdog_feed();
  uint16_t image_crc = crc16_region(APP_BASE, m.image_size);
  inherited_watchdog_feed();
  otah_settings_commit(BANK_VALID_APP_V, image_crc, m.image_size);
  gpregret2_set(0xB8);
  return finish_apply(true);

reject:
  clear_approval(&m);
  return finish_apply(false);
}
