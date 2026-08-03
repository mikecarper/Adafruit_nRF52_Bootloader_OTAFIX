// Raw-sector handoff written by MeshCore's OtaStoreSdNrf52. Keep byte-identical
// with MeshCore src/helpers/ota/OtaSdHandoff.h.
#ifndef OTA_SD_HANDOFF_H_
#define OTA_SD_HANDOFF_H_

#include <stdint.h>
#include <stddef.h>

#define MOTA_SD_SECTOR_SIZE       512u
#define MOTA_SD_HANDOFF_SECTOR    1u
#define MOTA_SD_HANDOFF_VERSION   1u
#define MOTA_SD_HANDOFF_LEN       36u

static const uint8_t MOTA_SD_HANDOFF_MAGIC[8] = {
  'M', 'O', 'T', 'A', 'S', 'D', '0', '1'
};

static inline uint32_t mota_sd_handoff_rd32(const uint8_t* p) {
  return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
         ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static inline uint32_t mota_sd_handoff_crc32(const uint8_t* data, size_t len) {
  uint32_t crc = 0xFFFFFFFFu;
  for (size_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (uint8_t bit = 0; bit < 8; bit++) {
      crc = (crc >> 1) ^ (0xEDB88320u & (uint32_t)-(int32_t)(crc & 1u));
    }
  }
  return ~crc;
}

#endif
