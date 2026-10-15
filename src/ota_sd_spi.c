#include "ota_sd_spi.h"

#if defined(MOTA_SD_CARD) && !defined(OTA_DELTA_HOST_TEST)

#include "nrf.h"
#include "nrf_gpio.h"
#include "nrf_wdt.h"
#include "watchdog.h"
#include "boards.h"
#include <string.h>
#if defined(MOTA_RAK_SD_STORE)
  #include "ota_rak_spi.h"
#endif

#ifndef MOTA_SD_SPIM
#define MOTA_SD_SPIM NRF_SPIM2
#endif

#ifndef MOTA_SD_SPI_WAIT_SPINS
#define MOTA_SD_SPI_WAIT_SPINS 100000u
#endif

static uint8_t g_tx;
static uint8_t g_rx;
static uint8_t g_sector[512];
static uint32_t g_sector_lba = UINT32_MAX;
static bool g_block_addressing;

#if defined(MOTA_RAK_SD_STORE)
static uint8_t g_spi_pins[4]; // CS, SCK, MOSI, MISO
static bool g_spi_ok;
#define g_io_ok g_spi_ok
#define spi_byte ota_rak_spi_byte

void ota_rak_spi_watchdog(void) {
  static uint16_t external_feed_divider;
  otafix_watchdog_feed();
  if ((external_feed_divider++ & 0x0FFFu) == 0) board_watchdog_feed();
}

void ota_rak_spi_set_frequency(uint32_t frequency) {
  MOTA_SD_SPIM->ENABLE = SPIM_ENABLE_ENABLE_Disabled;
  MOTA_SD_SPIM->FREQUENCY = frequency;
  MOTA_SD_SPIM->ENABLE = SPIM_ENABLE_ENABLE_Enabled;
}

bool ota_rak_spi_begin(uint8_t cs, uint8_t sck, uint8_t mosi, uint8_t miso, uint32_t frequency) {
  if ((cs | sck | mosi | miso) >= 32u) {
    g_spi_ok = false;
    return false;
  }
  g_spi_pins[0] = cs;
  g_spi_pins[1] = sck;
  g_spi_pins[2] = mosi;
  g_spi_pins[3] = miso;
  // Establish mode-0 idle levels and deselect BOTH supported devices before
  // output direction or clocks. RAK15001 and SD share CS26; no probe is made.
  NRF_P0->OUTSET = (1u << 26) | (1u << 31) | (1u << cs) | (1u << mosi);
  NRF_P0->OUTCLR = 1u << sck;
  // All reviewed RAK bus pins are P0. Preserve the NOR driver's high-drive
  // mode at 8 MHz instead of silently weakening SCK/MOSI in the shared path.
  const uint32_t output_config =
      (GPIO_PIN_CNF_DIR_Output << GPIO_PIN_CNF_DIR_Pos) |
      (GPIO_PIN_CNF_INPUT_Disconnect << GPIO_PIN_CNF_INPUT_Pos) |
      (GPIO_PIN_CNF_DRIVE_H0H1 << GPIO_PIN_CNF_DRIVE_Pos);
  NRF_P0->PIN_CNF[26] = output_config;
  NRF_P0->PIN_CNF[31] = output_config;
  for (uint32_t i = 0; i < 3u; ++i)
    NRF_P0->PIN_CNF[g_spi_pins[i]] = output_config;
  NRF_P0->PIN_CNF[miso] = (GPIO_PIN_CNF_INPUT_Connect << GPIO_PIN_CNF_INPUT_Pos) |
                           (GPIO_PIN_CNF_PULL_Pullup << GPIO_PIN_CNF_PULL_Pos);
  MOTA_SD_SPIM->ENABLE = SPIM_ENABLE_ENABLE_Disabled;
  MOTA_SD_SPIM->PSEL.SCK = sck;
  MOTA_SD_SPIM->PSEL.MOSI = mosi;
  MOTA_SD_SPIM->PSEL.MISO = miso;
  MOTA_SD_SPIM->CONFIG = 0;
  MOTA_SD_SPIM->ORC = 0xFF;
  ota_rak_spi_set_frequency(frequency);
  g_spi_ok = true;
  return true;
}

void ota_rak_spi_select(bool selected) {
  if (selected) NRF_P0->OUTCLR = 1u << g_spi_pins[0];
  else NRF_P0->OUTSET = 1u << g_spi_pins[0];
}

bool ota_rak_spi_healthy(void) { return g_spi_ok; }

// nRF52840 SPIM2 has an eight-bit EasyDMA MAXCNT. Every caller supplies RAM
// buffers; command bytes use the one-byte RAM globals below. The ORC clocks
// reads without allocating an equally large dummy transmit buffer.
__attribute__((noinline, noclone)) bool ota_rak_spi_transfer(const void *tx, void *rx, uint32_t length) {
  if (!g_spi_ok) return false;
  const uint8_t *input = tx;
  uint8_t *output = rx;
  while (length != 0u) {
    const uint32_t count = length > 255u ? 255u : length;
    ota_rak_spi_watchdog();
    MOTA_SD_SPIM->TXD.PTR = (uint32_t)(uintptr_t)input;
    MOTA_SD_SPIM->TXD.MAXCNT = input ? count : 0;
    MOTA_SD_SPIM->RXD.PTR = (uint32_t)(uintptr_t)output;
    MOTA_SD_SPIM->RXD.MAXCNT = output ? count : 0;
    MOTA_SD_SPIM->EVENTS_END = 0;
    __DMB(); // publish RAM command bytes before EasyDMA, including under LTO
    MOTA_SD_SPIM->TASKS_START = 1;
    uint32_t spins = MOTA_SD_SPI_WAIT_SPINS;
    while (!MOTA_SD_SPIM->EVENTS_END && spins-- != 0u) {
      if ((spins & 0x3FFu) == 0u) ota_rak_spi_watchdog();
    }
    if (!MOTA_SD_SPIM->EVENTS_END) {
      MOTA_SD_SPIM->TASKS_STOP = 1;
      MOTA_SD_SPIM->ENABLE = SPIM_ENABLE_ENABLE_Disabled;
      g_spi_ok = false;
      return false;
    }
    __DMB(); // DMA writes are not ordinary C stores visible to the optimizer
    if (input) input += count;
    if (output) output += count;
    length -= count;
  }
  return true;
}

uint8_t ota_rak_spi_byte(uint8_t value) {
  g_tx = value;
  g_rx = 0xFF;
  (void)ota_rak_spi_transfer(&g_tx, &g_rx, 1u);
  return g_rx;
}

void ota_rak_spi_release(bool keep_cs_high) {
  ota_rak_spi_select(false);
  MOTA_SD_SPIM->ENABLE = SPIM_ENABLE_ENABLE_Disabled;
  MOTA_SD_SPIM->PSEL.SCK = 0xFFFFFFFFu;
  MOTA_SD_SPIM->PSEL.MOSI = 0xFFFFFFFFu;
  MOTA_SD_SPIM->PSEL.MISO = 0xFFFFFFFFu;
  for (uint32_t i = keep_cs_high ? 1u : 0u; i < sizeof(g_spi_pins); ++i)
    NRF_P0->PIN_CNF[g_spi_pins[i]] = GPIO_PIN_CNF_INPUT_Disconnect << GPIO_PIN_CNF_INPUT_Pos;
  g_spi_ok = false;
}

#else
static bool g_io_ok;
static void feed_watchdogs(void) {
  static uint16_t external_feed_divider;
  otafix_watchdog_feed();
  if ((external_feed_divider++ & 0x0FFFu) == 0) {
    board_watchdog_feed();
  }
}

static uint8_t spi_byte(uint8_t value) {
  if (!g_io_ok) return 0xFF;
  feed_watchdogs();
  g_tx = value;
  MOTA_SD_SPIM->TXD.PTR = (uint32_t)(uintptr_t)&g_tx;
  MOTA_SD_SPIM->TXD.MAXCNT = 1;
  MOTA_SD_SPIM->RXD.PTR = (uint32_t)(uintptr_t)&g_rx;
  MOTA_SD_SPIM->RXD.MAXCNT = 1;
  MOTA_SD_SPIM->EVENTS_END = 0;
  MOTA_SD_SPIM->TASKS_START = 1;
  uint32_t spins = MOTA_SD_SPI_WAIT_SPINS;
  while (!MOTA_SD_SPIM->EVENTS_END && spins-- != 0) {
    if ((spins & 0x3FFu) == 0) feed_watchdogs();
  }
  if (!MOTA_SD_SPIM->EVENTS_END) {
    MOTA_SD_SPIM->TASKS_STOP = 1;
    g_io_ok = false;
    return 0xFF;
  }
  return g_rx;
}
#endif

static void deselect_card(void) {
#if defined(MOTA_RAK_SD_STORE)
  ota_rak_spi_select(false);
#else
  nrf_gpio_pin_set(MOTA_SD_CS_PIN);
#endif
  spi_byte(0xFF);
}

static bool select_card(void) {
#if defined(MOTA_RAK_SD_STORE)
  ota_rak_spi_select(true);
#else
  nrf_gpio_pin_clear(MOTA_SD_CS_PIN);
#endif
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
#if defined(MOTA_RAK_SD_STORE)
  // Two aligned little-endian words keep the six wire bytes in DMA RAM.
  const uint32_t frame[2] = {(__builtin_bswap32(arg) << 8) | (0x40u | cmd),
                              (uint8_t)arg | ((uint32_t)crc << 8)};
  if (!ota_rak_spi_transfer(frame, NULL, 6u)) {
    deselect_card();
    return 0xFF;
  }
#else
  spi_byte((uint8_t)(0x40u | cmd));
  spi_byte((uint8_t)(arg >> 24));
  spi_byte((uint8_t)(arg >> 16));
  spi_byte((uint8_t)(arg >> 8));
  spi_byte((uint8_t)arg);
  spi_byte(crc);
#endif
  for (uint8_t i = 0; i < 16; i++) {
    uint8_t r = spi_byte(0xFF);
    if (!(r & 0x80u)) return r;
  }
  return 0xFF;
}

bool ota_sd_init(void) {
  g_sector_lba = UINT32_MAX;
  g_io_ok = true;
#if defined(MOTA_RAK_SD_STORE)
  // Shared begin preloads and deselects CS26/31 before every clock.
  g_io_ok = ota_rak_spi_begin(MOTA_SD_CS_PIN, MOTA_SD_SCK_PIN,
                             MOTA_SD_MOSI_PIN, MOTA_SD_MISO_PIN,
                             SPIM_FREQUENCY_FREQUENCY_K250);
#else
  nrf_gpio_pin_set(MOTA_SD_CS_PIN);
  nrf_gpio_cfg_output(MOTA_SD_CS_PIN);
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
#endif

  for (uint8_t i = 0; i < 12; i++) spi_byte(0xFF);
  if (!g_io_ok) return false;
  uint8_t r = 0xFF;
  for (uint8_t i = 0; i < 20 && r != 0x01; i++) {
    r = command(0, 0, 0x95);
    deselect_card();
  }
  if (r != 0x01 || !g_io_ok) return false;

  bool v2 = false;
  r = command(8, 0x1AA, 0x87);
  if (r == 0x01) {
    uint8_t r7[4];
#if defined(MOTA_RAK_SD_STORE)
    if (!ota_rak_spi_transfer(NULL, r7, sizeof(r7))) {
      deselect_card();
      return false;
    }
#else
    for (uint8_t i = 0; i < 4; i++) r7[i] = spi_byte(0xFF);
#endif
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
  if (!ready || !g_io_ok) return false;

  r = command(58, 0, 0x01);
  if (r != 0) { deselect_card(); return false; }
  uint8_t ocr[4];
#if defined(MOTA_RAK_SD_STORE)
  if (!ota_rak_spi_transfer(NULL, ocr, sizeof(ocr))) {
    deselect_card();
    return false;
  }
#else
  for (uint8_t i = 0; i < 4; i++) ocr[i] = spi_byte(0xFF);
#endif
  deselect_card();
  if (!g_io_ok) return false;
  g_block_addressing = (ocr[0] & 0x40u) != 0;
  if (!g_block_addressing) {
    r = command(16, 512, 0x01);
    deselect_card();
    if (r != 0 || !g_io_ok) return false;
  }

#if defined(MOTA_RAK_SD_STORE)
  ota_rak_spi_set_frequency(SPIM_FREQUENCY_FREQUENCY_M8);
#else
  MOTA_SD_SPIM->ENABLE = SPIM_ENABLE_ENABLE_Disabled;
  MOTA_SD_SPIM->FREQUENCY = SPIM_FREQUENCY_FREQUENCY_M8;
  MOTA_SD_SPIM->ENABLE = SPIM_ENABLE_ENABLE_Enabled;
#endif
  return g_io_ok;
}

void ota_sd_deinit(void) {
  g_sector_lba = UINT32_MAX;
  g_io_ok = false;
#if defined(MOTA_RAK_SD_STORE)
  ota_rak_spi_release(false);
#else
  MOTA_SD_SPIM->ENABLE = SPIM_ENABLE_ENABLE_Disabled;
  MOTA_SD_SPIM->PSEL.SCK = 0xFFFFFFFFu;
  MOTA_SD_SPIM->PSEL.MOSI = 0xFFFFFFFFu;
  MOTA_SD_SPIM->PSEL.MISO = 0xFFFFFFFFu;
  nrf_gpio_cfg_default(MOTA_SD_CS_PIN);
  nrf_gpio_cfg_default(MOTA_SD_MOSI_PIN);
  nrf_gpio_cfg_default(MOTA_SD_SCK_PIN);
  nrf_gpio_cfg_default(MOTA_SD_MISO_PIN);
#endif
}

bool ota_sd_read_sector(uint32_t sector, uint8_t out[512]) {
  if (!g_io_ok || (!g_block_addressing && sector > UINT32_MAX / 512u)) return false;
  uint32_t arg = g_block_addressing ? sector : sector * 512u;
  for (uint8_t attempt = 0; attempt < 3; attempt++) {
    uint8_t r = command(17, arg, 0x01);
    if (r != 0) { deselect_card(); continue; }
    uint8_t token = 0xFF;
    for (uint32_t i = 0; i < 200000; i++) {
      token = spi_byte(0xFF);
      if (token != 0xFF) break;
    }
    if (token != 0xFE || !g_io_ok) { deselect_card(); continue; }
#if defined(MOTA_RAK_SD_STORE)
    if (!ota_rak_spi_transfer(NULL, out, 512u)) { deselect_card(); continue; }
#else
    for (uint32_t i = 0; i < 512; i++) out[i] = spi_byte(0xFF);
#endif
    spi_byte(0xFF); spi_byte(0xFF); // card CRC (transport integrity is rechecked by image SHA-256)
    deselect_card();
    return g_io_ok;
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
