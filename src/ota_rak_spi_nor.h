// Implementation included only by ota_qspi.c for MOTA_RAK_SD_STORE. The two
// RAK NOR layouts use ordinary single-line SPI, so SD and NOR can share one
// bounded SPIM2 transport without probing or owning the other device.
#include "ota_rak_spi.h"
#include "boards.h"
#include "nrf.h"
#include "nrf_gpio.h"
#include "nrf_delay.h"
#include <string.h>

static bool g_nor_active;
static uint32_t g_nor_capacity;
static uint8_t g_nor_source;

static bool nor_command(uint8_t opcode) {
  ota_rak_spi_select(true);
  (void)ota_rak_spi_byte(opcode);
  ota_rak_spi_select(false);
  return ota_rak_spi_healthy();
}

static uint8_t nor_status(void) {
  ota_rak_spi_select(true);
  (void)ota_rak_spi_byte(0x05);
  const uint8_t status = ota_rak_spi_byte(0xFF);
  ota_rak_spi_select(false);
  return status;
}

static bool nor_wait_ready(uint32_t steps) {
  while (steps-- != 0u) {
    ota_rak_spi_watchdog();
    const uint8_t status = nor_status();
    if (!ota_rak_spi_healthy()) return false;
    if ((status & 1u) == 0u) return true;
    nrf_delay_us(10u);
  }
  return false;
}

void ota_qspi_set_rak_source(uint8_t stage_handoff) {
  g_nor_source = stage_handoff;
}

void ota_qspi_deinit(void) {
  if (!g_nor_active) return;
  // Never sleep a part whose status cannot prove an interrupted erase/write
  // finished. Its unswitched rail remains present and CS stays driven high.
  const bool released = nor_wait_ready(500000u) && nor_command(0xB9);
  if (released) nrf_delay_us(50u);
  ota_rak_spi_release(!released);
  g_nor_active = false;
  g_nor_capacity = 0;
}

bool ota_qspi_init(void) {
  if (g_nor_capacity != 0u) return true;
  if (g_nor_source != GPREGRET2_OTA_STAGE_QSPI &&
      g_nor_source != GPREGRET2_OTA_STAGE_RAK15001 &&
      g_nor_source != GPREGRET2_OTA_STAGE_HEADER_W25) return false;
  // Shared begin preloads both physical chip selects before any bus clocks.
  const bool header = g_nor_source == GPREGRET2_OTA_STAGE_HEADER_W25;
  const uint8_t cs = g_nor_source == GPREGRET2_OTA_STAGE_RAK15001 ? 26u : 31u;
  if (!ota_rak_spi_begin(cs, header ? 16u : 3u, header ? 17u : 30u,
                         header ? 15u : 29u, SPIM_FREQUENCY_FREQUENCY_M8)) return false;
  g_nor_active = true;
  nrf_delay_us(50u);
  (void)nor_command(0xAB);
  nrf_delay_us(50u);
  if (!ota_rak_spi_healthy() || !nor_wait_ready(500000u)) goto failed;

  uint8_t jedec[3];
  ota_rak_spi_select(true);
  (void)ota_rak_spi_byte(0x9F);
  const bool read = ota_rak_spi_transfer(NULL, jedec, sizeof(jedec));
  ota_rak_spi_select(false);
  if (!read || jedec[0] != (cs == 26u ? 0xC8u : 0xEFu) ||
      jedec[1] != 0x40u || jedec[2] != 0x15u) goto failed;
  g_nor_capacity = 1u << 21;
  return true;
failed:
  ota_qspi_deinit();
  return false;
}

uint32_t ota_qspi_capacity(void) { return g_nor_capacity; }

static bool nor_address(uint8_t opcode, uint32_t address) {
  // nRF52840 is little-endian and every caller bounds the NOR address to
  // 2 MiB. REV packs opcode + three address bytes in one RAM/DMA word.
  const uint32_t header = __builtin_bswap32(address) | opcode;
  ota_rak_spi_select(true);
  return ota_rak_spi_transfer(&header, NULL, sizeof(header));
}

bool ota_qspi_read(uint32_t offset, void *dst, uint32_t len) {
  if (!g_nor_capacity || !dst || offset > g_nor_capacity || len > g_nor_capacity - offset)
    return false;
  if (len == 0u) return true;
  // FASTREAD is single-line 0Bh plus one dummy byte on the existing RAK NORs.
  bool ok = nor_address(0x0B, offset);
  (void)ota_rak_spi_byte(0xFF);
  ok = ok && ota_rak_spi_transfer(NULL, dst, len);
  ota_rak_spi_select(false);
  return ok;
}

bool ota_qspi_write(uint32_t offset, const void *src, uint32_t len) {
  // Preserve the public purpose-specific API: only one four-byte approval
  // word, no arbitrary writer or erase command. Unlike QSPI, SPIM has no
  // four-byte DMA alignment requirement: never address adjacent NOR bytes.
  if (!g_nor_capacity || !src || len != 4u || (offset & 255u) + len > 256u ||
      offset > g_nor_capacity || len > g_nor_capacity - offset) return false;
  uint8_t expected[4], verify[4];
  if (!ota_qspi_read(offset, expected, sizeof(expected)) ||
      !ota_qspi_nor_overlay(expected, sizeof(expected), 0, src, len) ||
      !nor_command(0x06) || (nor_status() & 3u) != 2u || !ota_rak_spi_healthy()) return false;
  bool ok = nor_address(0x02, offset) && ota_rak_spi_transfer(expected, NULL, sizeof(expected));
  ota_rak_spi_select(false);
  return ok && nor_wait_ready(10000u) && ota_qspi_read(offset, verify, sizeof(verify)) &&
         memcmp(verify, expected, sizeof(expected)) == 0;
}
