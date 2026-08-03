#include "ota_sd_spi.h"

#if defined(MOTA_SD_CARD) && !defined(OTA_DELTA_HOST_TEST)

#include "nrf.h"
#include "nrf_gpio.h"
#include "boards.h"
#include <string.h>

#ifndef MOTA_SD_SPIM
#define MOTA_SD_SPIM NRF_SPIM2
#endif

static uint8_t g_tx;
static uint8_t g_rx;
static uint8_t g_sector[512];
static uint32_t g_sector_lba = UINT32_MAX;
static bool g_block_addressing;

static uint8_t spi_byte(uint8_t value) {
  g_tx = value;
  MOTA_SD_SPIM->TXD.PTR = (uint32_t)(uintptr_t)&g_tx;
  MOTA_SD_SPIM->TXD.MAXCNT = 1;
  MOTA_SD_SPIM->RXD.PTR = (uint32_t)(uintptr_t)&g_rx;
  MOTA_SD_SPIM->RXD.MAXCNT = 1;
  MOTA_SD_SPIM->EVENTS_END = 0;
  MOTA_SD_SPIM->TASKS_START = 1;
  while (!MOTA_SD_SPIM->EVENTS_END) {}
  return g_rx;
}

static void deselect_card(void) {
  nrf_gpio_pin_set(MOTA_SD_CS_PIN);
  spi_byte(0xFF);
}

static bool select_card(void) {
  nrf_gpio_pin_clear(MOTA_SD_CS_PIN);
  for (uint32_t i = 0; i < 2048; i++) {
    if (spi_byte(0xFF) == 0xFF) return true;
  }
  deselect_card();
  return false;
}

// Send one command and leave CS asserted so callers may read response data.
static uint8_t command(uint8_t cmd, uint32_t arg, uint8_t crc) {
  deselect_card();
  if (!select_card()) return 0xFF;
  spi_byte((uint8_t)(0x40u | cmd));
  spi_byte((uint8_t)(arg >> 24));
  spi_byte((uint8_t)(arg >> 16));
  spi_byte((uint8_t)(arg >> 8));
  spi_byte((uint8_t)arg);
  spi_byte(crc);
  for (uint8_t i = 0; i < 16; i++) {
    uint8_t r = spi_byte(0xFF);
    if (!(r & 0x80u)) return r;
  }
  return 0xFF;
}

bool ota_sd_init(void) {
  g_sector_lba = UINT32_MAX;
  nrf_gpio_cfg_output(MOTA_SD_CS_PIN);
  nrf_gpio_pin_set(MOTA_SD_CS_PIN);
  nrf_gpio_cfg_output(MOTA_SD_MOSI_PIN);
  nrf_gpio_cfg_output(MOTA_SD_SCK_PIN);
  nrf_gpio_cfg_input(MOTA_SD_MISO_PIN, NRF_GPIO_PIN_PULLUP);

  MOTA_SD_SPIM->ENABLE = SPIM_ENABLE_ENABLE_Disabled;
  MOTA_SD_SPIM->PSEL.SCK = MOTA_SD_SCK_PIN;
  MOTA_SD_SPIM->PSEL.MOSI = MOTA_SD_MOSI_PIN;
  MOTA_SD_SPIM->PSEL.MISO = MOTA_SD_MISO_PIN;
  MOTA_SD_SPIM->FREQUENCY = SPIM_FREQUENCY_FREQUENCY_K250;
  MOTA_SD_SPIM->CONFIG = 0;
  MOTA_SD_SPIM->ORC = 0xFF;
  MOTA_SD_SPIM->ENABLE = SPIM_ENABLE_ENABLE_Enabled;

  for (uint8_t i = 0; i < 12; i++) spi_byte(0xFF);
  uint8_t r = 0xFF;
  for (uint8_t i = 0; i < 20 && r != 0x01; i++) {
    r = command(0, 0, 0x95);
    deselect_card();
  }
  if (r != 0x01) return false;

  bool v2 = false;
  r = command(8, 0x1AA, 0x87);
  if (r == 0x01) {
    uint8_t r7[4];
    for (uint8_t i = 0; i < 4; i++) r7[i] = spi_byte(0xFF);
    v2 = r7[2] == 0x01 && r7[3] == 0xAA;
  } else if (!(r & 0x04u)) {
    deselect_card();
    return false;
  }
  deselect_card();

  bool ready = false;
  for (uint32_t i = 0; i < 4000; i++) {
    r = command(55, 0, 0x01); deselect_card();
    if (r > 0x01) break;
    r = command(41, v2 ? 0x40000000u : 0, 0x01); deselect_card();
    if (r == 0) { ready = true; break; }
  }
  if (!ready) return false;

  r = command(58, 0, 0x01);
  if (r != 0) { deselect_card(); return false; }
  uint8_t ocr[4];
  for (uint8_t i = 0; i < 4; i++) ocr[i] = spi_byte(0xFF);
  deselect_card();
  g_block_addressing = (ocr[0] & 0x40u) != 0;
  if (!g_block_addressing) {
    r = command(16, 512, 0x01);
    deselect_card();
    if (r != 0) return false;
  }

  MOTA_SD_SPIM->ENABLE = SPIM_ENABLE_ENABLE_Disabled;
  MOTA_SD_SPIM->FREQUENCY = SPIM_FREQUENCY_FREQUENCY_M8;
  MOTA_SD_SPIM->ENABLE = SPIM_ENABLE_ENABLE_Enabled;
  return true;
}

void ota_sd_deinit(void) {
  g_sector_lba = UINT32_MAX;
  MOTA_SD_SPIM->ENABLE = SPIM_ENABLE_ENABLE_Disabled;
  MOTA_SD_SPIM->PSEL.SCK = 0xFFFFFFFFu;
  MOTA_SD_SPIM->PSEL.MOSI = 0xFFFFFFFFu;
  MOTA_SD_SPIM->PSEL.MISO = 0xFFFFFFFFu;
  nrf_gpio_cfg_default(MOTA_SD_CS_PIN);
  nrf_gpio_cfg_default(MOTA_SD_MOSI_PIN);
  nrf_gpio_cfg_default(MOTA_SD_SCK_PIN);
  nrf_gpio_cfg_default(MOTA_SD_MISO_PIN);
}

bool ota_sd_read_sector(uint32_t sector, uint8_t out[512]) {
  if (!g_block_addressing && sector > UINT32_MAX / 512u) return false;
  uint32_t arg = g_block_addressing ? sector : sector * 512u;
  for (uint8_t attempt = 0; attempt < 3; attempt++) {
    uint8_t r = command(17, arg, 0x01);
    if (r != 0) { deselect_card(); continue; }
    uint8_t token = 0xFF;
    for (uint32_t i = 0; i < 200000; i++) {
      token = spi_byte(0xFF);
      if (token != 0xFF) break;
    }
    if (token != 0xFE) { deselect_card(); continue; }
    for (uint32_t i = 0; i < 512; i++) out[i] = spi_byte(0xFF);
    spi_byte(0xFF); spi_byte(0xFF); // card CRC (transport integrity is rechecked by image SHA-256)
    deselect_card();
    return true;
  }
  return false;
}

bool ota_sd_read_bytes(uint32_t first_sector, uint32_t offset,
                       void* out, uint32_t len) {
  uint8_t* dst = (uint8_t*)out;
  while (len) {
    uint32_t sector_off = offset & 511u;
    uint32_t n = 512u - sector_off;
    if (n > len) n = len;
    uint32_t lba = first_sector + (offset >> 9);
    if (lba < first_sector) return false;
    if (lba != g_sector_lba) {
      if (!ota_sd_read_sector(lba, g_sector)) return false;
      g_sector_lba = lba;
    }
    memcpy(dst, g_sector + sector_off, n);
    dst += n;
    offset += n;
    len -= n;
  }
  return true;
}

#endif
