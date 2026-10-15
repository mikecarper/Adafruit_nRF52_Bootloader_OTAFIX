// Validate both retained-record ABIs independently of the storage dispatch.
// Compile with and without MOTA_RAK_SD_STORE to hold shared and legacy paths
// to the same envelope/geometry contract.
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "ota_sd_auth.h"
#include "ota_hybrid_handoff.h"

static unsigned checks;
static int failed;

static void expect(int condition, const char *name, unsigned index) {
  checks++;
  if (!condition) {
    fprintf(stderr, "FAIL %s[%u]\n", name, index);
    failed = 1;
  }
}

static void repair_crc(void *record) {
  uint8_t *bytes = record;
  const uint32_t crc = otafix_crc32_update(0, bytes, 64u);
  const uint32_t inverse = ~crc;
  memcpy(bytes + 64u, &crc, sizeof(crc));
  memcpy(bytes + 68u, &inverse, sizeof(inverse));
}

int main(void) {
  uint8_t digest[32];
  for (unsigned i = 0; i < sizeof(digest); i++) digest[i] = (uint8_t)(i * 7u + 3u);
  mota_sd_auth_t sd;
  mota_hybrid_handoff_t hybrid;
  mota_sd_auth_encode(&sd, 1u, 2u, 128u, 2u, 513u, 4096u, digest);
  mota_hybrid_handoff_encode(&hybrid, 66560u, 0xD0000u, 65536u, 1024u, digest);
  expect(mota_sd_auth_valid(&sd, 1u, 2u), "valid SD", 0);
  expect(mota_hybrid_handoff_valid(&hybrid), "valid hybrid", 0);
  expect(!mota_sd_auth_valid(NULL, 1u, 2u), "NULL SD", 0);
  expect(!mota_hybrid_handoff_valid(NULL), "NULL hybrid", 0);

  // Every byte, including digest, CRC and inverse, must remain bound to the
  // original record. This includes all magic and metadata/reserved bytes.
  for (unsigned i = 0; i < sizeof(sd); i++) {
    mota_sd_auth_t changed = sd;
    ((uint8_t *)&changed)[i] ^= 1u;
    expect(!mota_sd_auth_valid(&changed, 1u, 2u), "SD byte corruption", i);
    mota_hybrid_handoff_t changed_hybrid = hybrid;
    ((uint8_t *)&changed_hybrid)[i] ^= 1u;
    expect(!mota_hybrid_handoff_valid(&changed_hybrid), "hybrid byte corruption", i);
  }
  // Recompute CRCs after changing each metadata byte: semantic checks must not
  // be accidentally replaced by the shared CRC check alone.
  for (unsigned i = 0; i < 16u; i++) {
    mota_sd_auth_t changed = sd;
    ((uint8_t *)&changed)[i] ^= 1u;
    repair_crc(&changed);
    expect(!mota_sd_auth_valid(&changed, 1u, 2u), "SD metadata", i);
    mota_hybrid_handoff_t changed_hybrid = hybrid;
    ((uint8_t *)&changed_hybrid)[i] ^= 1u;
    repair_crc(&changed_hybrid);
    expect(!mota_hybrid_handoff_valid(&changed_hybrid), "hybrid metadata", i);
  }
  for (unsigned i = 0; i < 10u; i++) {
    mota_sd_auth_t changed = sd;
    switch (i) {
      case 0: changed.first_sector = 0; break;
      case 1: changed.sector_count = 0; break;
      case 2: changed.container_total = 0; break;
      case 3: changed.card_sector_count = 0; break;
      case 4: changed.first_sector = changed.card_sector_count; break;
      case 5: changed.sector_count = changed.card_sector_count; break;
      case 6: changed.card_sector_count = changed.first_sector + 1u; break;
      case 7: changed.container_total = 512u; break;
      case 8: changed.container_total = 1025u; break;
      default:
        changed.first_sector = UINT32_MAX - 1u;
        changed.card_sector_count = UINT32_MAX;
        break;
    }
    repair_crc(&changed);
    expect(!mota_sd_auth_valid(&changed, 1u, 2u), "SD geometry", i);
  }
  for (unsigned i = 0; i < 5u; i++) {
    mota_hybrid_handoff_t changed = hybrid;
    switch (i) {
      case 0: changed.flash_len = 0; break;
      case 1: changed.ram_len = 0; break;
      case 2: changed.ram_len = MOTA_HYBRID_ARENA_SIZE + 1u; break;
      case 3: changed.container_total++; break;
      default:
        changed.flash_len = UINT32_MAX;
        changed.ram_len = 1u;
        changed.container_total = 0u;
        break;
    }
    repair_crc(&changed);
    expect(!mota_hybrid_handoff_valid(&changed), "hybrid geometry", i);
  }

  // The arithmetic permits the largest non-overflowing source envelope;
  // runtime policy still bounds actual media capacity and exact flash range.
  mota_sd_auth_t edge_sd;
  mota_sd_auth_encode(&edge_sd, 1u, 2u, UINT32_MAX - 2u, 2u, 1024u, UINT32_MAX, digest);
  expect(mota_sd_auth_valid(&edge_sd, 1u, 2u), "SD nonoverflow edge", 0);
  mota_hybrid_handoff_t edge_hybrid;
  mota_hybrid_handoff_encode(&edge_hybrid, UINT32_MAX, 0xD0000u,
      UINT32_MAX - MOTA_HYBRID_ARENA_SIZE, MOTA_HYBRID_ARENA_SIZE, digest);
  expect(mota_hybrid_handoff_valid(&edge_hybrid), "hybrid nonoverflow edge", 0);
  // Payload hash content is authenticated by the caller's retained record,
  // then compared with the actual source by the applier, not by this helper.
  sd.container_sha256[0] ^= 1u;
  repair_crc(&sd);
  expect(mota_sd_auth_valid(&sd, 1u, 2u), "rebound SD digest", 0);
  hybrid.container_sha256[0] ^= 1u;
  repair_crc(&hybrid);
  expect(mota_hybrid_handoff_valid(&hybrid), "rebound hybrid digest", 0);
  expect(!mota_sd_auth_valid(&sd, 2u, 2u) && !mota_sd_auth_valid(&sd, 1u, 3u),
      "SD expected purpose/format", 0);
  mota_sd_auth_encode(&edge_sd, 2u, 3u, 128u, 2u, 513u, 4096u, digest);
  expect(mota_sd_auth_valid(&edge_sd, 2u, 3u), "SD explicit purpose/format", 0);

  printf("retained SD/hybrid envelope checks=%u: %s\n", checks, failed ? "FAIL" : "PASS");
  return failed ? 1 : 0;
}
