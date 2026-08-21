#include "ota_qspi.h"
#include "ota_qspi_alignment.h"

#if defined(MOTA_QSPI_FLASH) && !defined(OTA_DELTA_HOST_TEST)

  #include <string.h>
  #include "boards.h"
  #include "hal/nrf_qspi.h"
  #include "nrf_delay.h"

  #define QSPI_APPROVAL_LEN 4u
  #define QSPI_DPD_ENTER    0xB9u
  #define QSPI_DPD_T_US     5u
  #define QSPI_MAX_CAPACITY 0x01000000u
  #define QSPI_WAIT_STEPS   3000000u

  #ifndef MOTA_QSPI_SCK_FREQ
    #define MOTA_QSPI_SCK_FREQ NRF_QSPI_FREQ_32MDIV2
  #endif

  #if (defined(MOTA_QSPI_JEDEC_MANUFACTURER) || defined(MOTA_QSPI_JEDEC_MEMORY_TYPE) || \
       defined(MOTA_QSPI_JEDEC_CAPACITY)) && \
    !(defined(MOTA_QSPI_JEDEC_MANUFACTURER) && defined(MOTA_QSPI_JEDEC_MEMORY_TYPE) && \
      defined(MOTA_QSPI_JEDEC_CAPACITY))
    #error "Define all three MOTA_QSPI_JEDEC_* bytes or none of them"
  #endif

static bool     g_initialized;
static bool     g_active;
static bool     g_awake;
static uint32_t g_capacity;
static uint8_t  g_bounce[256] __attribute__((aligned(4)));
#if defined(MOTA_QSPI_POWER_PIN)
static bool g_powered;
#endif

_Static_assert((sizeof(g_bounce) & (OTA_QSPI_DMA_ALIGNMENT - 1u)) == 0,
               "QSPI bounce buffer size must be word aligned");

static void feed_watchdogs(void) {
  if (NRF_WDT->RUNSTATUS != 0) {
    const uint32_t enabled = NRF_WDT->RREN & 0xFFu;
    for (uint8_t channel = 0; channel < 8; channel++) {
      if ((enabled & (1u << channel)) != 0) {
        NRF_WDT->RR[channel] = WDT_RR_RR_Reload;
      }
    }
  }
  board_watchdog_feed();
}

static bool wait_ready(void) {
  for (uint32_t step = 0; step < QSPI_WAIT_STEPS; step++) {
    if (nrf_qspi_event_check(NRF_QSPI, NRF_QSPI_EVENT_READY)) {
      nrf_qspi_event_clear(NRF_QSPI, NRF_QSPI_EVENT_READY);
      return true;
    }
    if ((step & 0x3FFu) == 0) {
      feed_watchdogs();
    }
    nrf_delay_us(10);
  }
  return false;
}

static bool custom_instruction(uint8_t opcode, nrf_qspi_cinstr_len_t length, uint8_t *rx) {
  nrf_qspi_cinstr_conf_t config;
  memset(&config, 0, sizeof(config));
  config.opcode    = opcode;
  config.length    = length;
  config.io2_level = true;
  config.io3_level = true;
  nrf_qspi_event_clear(NRF_QSPI, NRF_QSPI_EVENT_READY);
  nrf_qspi_cinstr_transfer_start(NRF_QSPI, &config);
  if (!wait_ready()) {
    return false;
  }
  if (rx != NULL) {
    nrf_qspi_cinstrdata_get(NRF_QSPI, length, rx);
  }
  return true;
}

bool ota_qspi_init(void) {
  if (g_initialized) {
    return true;
  }
  g_capacity = 0;
  g_awake = false;

  #if defined(MOTA_QSPI_POWER_PIN)
  nrf_gpio_cfg_output(MOTA_QSPI_POWER_PIN);
  nrf_gpio_pin_write(MOTA_QSPI_POWER_PIN, MOTA_QSPI_POWER_ACTIVE);
  g_powered = true;
  nrf_delay_ms(2);
  #endif

  nrf_qspi_int_disable(NRF_QSPI, 0xFFFFFFFFu);
  NVIC_DisableIRQ(QSPI_IRQn);
  NVIC_ClearPendingIRQ(QSPI_IRQn);

  const nrf_qspi_pins_t pins = {
    .sck_pin = MOTA_QSPI_SCK_PIN,
    .csn_pin = MOTA_QSPI_CSN_PIN,
    .io0_pin = MOTA_QSPI_IO0_PIN,
    .io1_pin = MOTA_QSPI_IO1_PIN,
    .io2_pin = MOTA_QSPI_IO2_PIN,
    .io3_pin = MOTA_QSPI_IO3_PIN,
  };
  nrf_qspi_pins_set(NRF_QSPI, &pins);

  const nrf_qspi_prot_conf_t protocol = {
    .readoc    = NRF_QSPI_READOC_FASTREAD,
    .writeoc   = NRF_QSPI_WRITEOC_PP,
    .addrmode  = NRF_QSPI_ADDRMODE_24BIT,
    .dpmconfig = false,
  };
  nrf_qspi_ifconfig0_set(NRF_QSPI, &protocol);

  const nrf_qspi_phy_conf_t physical = {
    .sck_freq  = MOTA_QSPI_SCK_FREQ,
    .sck_delay = 5,
    .spi_mode  = NRF_QSPI_MODE_0,
    .dpmen     = false,
  };
  nrf_qspi_ifconfig1_set(NRF_QSPI, &physical);

  nrf_qspi_enable(NRF_QSPI);
  g_active = true;
  nrf_qspi_event_clear(NRF_QSPI, NRF_QSPI_EVENT_READY);
  nrf_qspi_task_trigger(NRF_QSPI, NRF_QSPI_TASK_ACTIVATE);
  if (!wait_ready()) {
    ota_qspi_deinit();
    return false;
  }
  if (!custom_instruction(0xAB, NRF_QSPI_CINSTR_LEN_1B, NULL)) {
    ota_qspi_deinit();
    return false;
  }
  g_awake = true;
  nrf_delay_us(50);

  uint8_t jedec[4] __attribute__((aligned(4))) = {0, 0, 0, 0};
  if (!custom_instruction(0x9F, NRF_QSPI_CINSTR_LEN_4B, jedec) || jedec[0] == 0 || jedec[0] == 0xFF || jedec[2] < 20 ||
      jedec[2] > 24) {
    ota_qspi_deinit();
    return false;
  }
  #if defined(MOTA_QSPI_JEDEC_MANUFACTURER)
  if (jedec[0] != MOTA_QSPI_JEDEC_MANUFACTURER || jedec[1] != MOTA_QSPI_JEDEC_MEMORY_TYPE ||
      jedec[2] != MOTA_QSPI_JEDEC_CAPACITY) {
    ota_qspi_deinit();
    return false;
  }
  #endif
  g_capacity = 1u << jedec[2];
  if (g_capacity > QSPI_MAX_CAPACITY) {
    ota_qspi_deinit();
    return false;
  }
  g_initialized = true;
  return true;
}

void ota_qspi_deinit(void) {
  if (g_awake && g_active) {
    // The application may run immediately after a rejected handoff without a
    // reset. Balance every completed 0xAB wake with deep power-down, including
    // a later JEDEC validation failure; the next access wakes it again.
    (void)custom_instruction(QSPI_DPD_ENTER, NRF_QSPI_CINSTR_LEN_1B, NULL);
    nrf_delay_us(QSPI_DPD_T_US);
  }
  g_awake = false;
  if (g_active) {
    nrf_qspi_event_clear(NRF_QSPI, NRF_QSPI_EVENT_READY);
    nrf_qspi_task_trigger(NRF_QSPI, NRF_QSPI_TASK_DEACTIVATE);
    nrf_qspi_disable(NRF_QSPI);
    nrf_qspi_event_clear(NRF_QSPI, NRF_QSPI_EVENT_READY);
  }
  g_active = false;
  g_initialized = false;
  g_capacity = 0;

  #if defined(MOTA_QSPI_POWER_PIN)
  if (g_powered) {
    nrf_gpio_pin_write(MOTA_QSPI_POWER_PIN, MOTA_QSPI_POWER_ACTIVE ? 0u : 1u);
    g_powered = false;
  }
  #endif
}

uint32_t ota_qspi_capacity(void) {
  return g_initialized ? g_capacity : 0;
}

static bool read_aligned(uint32_t offset, uint8_t *dst, uint32_t len) {
  if ((offset & (OTA_QSPI_DMA_ALIGNMENT - 1u)) != 0 ||
      ((uintptr_t)dst & (OTA_QSPI_DMA_ALIGNMENT - 1u)) != 0 ||
      (len & (OTA_QSPI_DMA_ALIGNMENT - 1u)) != 0 || len == 0 ||
      (uint64_t)offset + len > g_capacity) {
    return false;
  }
  nrf_qspi_read_buffer_set(NRF_QSPI, dst, len, offset);
  nrf_qspi_event_clear(NRF_QSPI, NRF_QSPI_EVENT_READY);
  nrf_qspi_task_trigger(NRF_QSPI, NRF_QSPI_TASK_READSTART);
  return wait_ready();
}

static bool write_aligned(uint32_t offset, const uint8_t *src, uint32_t len) {
  if ((offset & (OTA_QSPI_DMA_ALIGNMENT - 1u)) != 0 ||
      ((uintptr_t)src & (OTA_QSPI_DMA_ALIGNMENT - 1u)) != 0 ||
      (len & (OTA_QSPI_DMA_ALIGNMENT - 1u)) != 0 || len == 0 ||
      (offset & 255u) + len > 256u || (uint64_t)offset + len > g_capacity) {
    return false;
  }
  nrf_qspi_write_buffer_set(NRF_QSPI, src, len, offset);
  nrf_qspi_event_clear(NRF_QSPI, NRF_QSPI_EVENT_READY);
  nrf_qspi_task_trigger(NRF_QSPI, NRF_QSPI_TASK_WRITESTART);
  return wait_ready();
}

bool ota_qspi_read(uint32_t offset, void *dst, uint32_t len) {
  if (!g_initialized || dst == NULL || (uint64_t)offset + len > g_capacity) {
    return false;
  }
  uint8_t *out = (uint8_t *)dst;
  while (len != 0) {
    ota_qspi_dma_window_t window;
    if (!ota_qspi_dma_window(offset, len, g_capacity, sizeof(g_bounce), &window) ||
        !read_aligned(window.offset, g_bounce, window.length)) {
      return false;
    }
    memcpy(out, g_bounce + window.prefix, window.copy_length);
    offset += window.copy_length;
    out += window.copy_length;
    len -= window.copy_length;
  }
  return true;
}

bool ota_qspi_write(uint32_t offset, const void *src, uint32_t len) {
  // The bootloader only clears the four-byte approval word. Keep this helper
  // purpose-specific instead of carrying a general NOR writer.
  if (!g_initialized || src == NULL || len != QSPI_APPROVAL_LEN || (offset & 255u) + len > 256u ||
      (uint64_t)offset + len > g_capacity) {
    return false;
  }

  ota_qspi_dma_window_t window;
  if (!ota_qspi_dma_window(offset, len, g_capacity, sizeof(g_bounce), &window) ||
      window.copy_length != len || !read_aligned(window.offset, g_bounce, window.length) ||
      !ota_qspi_nor_overlay(g_bounce, window.length, window.prefix, src, len)) {
    return false;
  }

  uint8_t expected[2u * OTA_QSPI_DMA_ALIGNMENT] __attribute__((aligned(4)));
  uint8_t verify[2u * OTA_QSPI_DMA_ALIGNMENT] __attribute__((aligned(4)));
  if (window.length > sizeof(expected)) {
    return false;
  }
  memcpy(expected, g_bounce, window.length);
  return write_aligned(window.offset, g_bounce, window.length) &&
         read_aligned(window.offset, verify, window.length) &&
         memcmp(verify, expected, window.length) == 0;
}

#endif
