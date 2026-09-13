#include "ota_qspi.h"
#include "ota_qspi_alignment.h"
#include "ota_qspi_wake.h"

#if defined(MOTA_QSPI_FLASH) && !defined(OTA_DELTA_HOST_TEST)

  #include <string.h>
  #include "boards.h"
  #include "hal/nrf_qspi.h"
  #include "nrf_delay.h"
  #include "watchdog.h"

  #define QSPI_APPROVAL_LEN 4u
  #define QSPI_DPD_ENTER            0xB9u
  #define QSPI_READ_STATUS          0x05u
  #define QSPI_STATUS_WIP           0x01u
  // MX25R1635F requires tDP (10 us) plus tDPDD (30 us) with CS# high
  // before another command may be issued after entering deep power-down.
  // Keep 10 us of margin and match the application's release guard.
  #define QSPI_DPD_RELEASE_GUARD_US 50u
  #define QSPI_MAX_CAPACITY 0x01000000u
  #define QSPI_WAIT_STEPS   3000000u
  // READY after WRITESTART only means that the QSPI peripheral transferred
  // the page-program command and data. The serial NOR can remain busy for
  // milliseconds afterward, so poll its status before verifying or sleeping.
  #define QSPI_PROGRAM_WAIT_STEP_US 10u
  #define QSPI_PROGRAM_WAIT_STEPS   10000u
  // A reset can hand control to the bootloader while a staging sector erase
  // started by the application is still in progress. Allow substantially
  // longer than the worst sector-erase time of the supported NOR parts.
  #define QSPI_RECOVERY_WAIT_STEPS 500000u
  #define QSPI_PIN_CNF_DEFAULT \
    (GPIO_PIN_CNF_INPUT_Disconnect << GPIO_PIN_CNF_INPUT_Pos)
  #define QSPI_PIN_CNF_H0H1 \
    (QSPI_PIN_CNF_DEFAULT | (GPIO_PIN_CNF_DRIVE_H0H1 << GPIO_PIN_CNF_DRIVE_Pos))
  #define QSPI_PIN_CNF_OUTPUT_H0H1 \
    (QSPI_PIN_CNF_H0H1 | (GPIO_PIN_CNF_DIR_Output << GPIO_PIN_CNF_DIR_Pos))
  #define QSPI_GPIO_PORT(pin) (((pin) & 32u) != 0 ? NRF_P1 : NRF_P0)
  #define QSPI_GPIO_INDEX(pin) ((pin) & 31u)

  #ifndef MOTA_QSPI_SCK_FREQ
    #define MOTA_QSPI_SCK_FREQ NRF_QSPI_FREQ_32MDIV2
  #endif

  #if (defined(MOTA_QSPI_JEDEC_MANUFACTURER) || defined(MOTA_QSPI_JEDEC_MEMORY_TYPE) || \
       defined(MOTA_QSPI_JEDEC_CAPACITY)) && \
    !(defined(MOTA_QSPI_JEDEC_MANUFACTURER) && defined(MOTA_QSPI_JEDEC_MEMORY_TYPE) && \
      defined(MOTA_QSPI_JEDEC_CAPACITY))
    #error "Define all three MOTA_QSPI_JEDEC_* bytes or none of them"
  #endif

static bool     g_active;
static bool     g_awake;
static uint32_t g_capacity;
static uint8_t  g_bounce[256] __attribute__((aligned(4)));

_Static_assert((sizeof(g_bounce) & (OTA_QSPI_DMA_ALIGNMENT - 1u)) == 0,
               "QSPI bounce buffer size must be word aligned");
_Static_assert(QSPI_DPD_RELEASE_GUARD_US >= 50u,
               "QSPI deep-power-down release guard must retain timing margin");
_Static_assert(OTA_QSPI_WAKE_GUARD_US >= 50u,
               "QSPI pre-activation wake guard must retain timing margin");
_Static_assert(QSPI_PROGRAM_WAIT_STEP_US * QSPI_PROGRAM_WAIT_STEPS >= 100000u,
               "QSPI page-program wait must retain a conservative timeout");
_Static_assert(QSPI_PROGRAM_WAIT_STEP_US * QSPI_RECOVERY_WAIT_STEPS >= 5000000u,
               "QSPI recovery wait must cover an interrupted sector erase");
_Static_assert(MOTA_QSPI_SCK_PIN != NRF_QSPI_PIN_NOT_CONNECTED &&
                 MOTA_QSPI_CSN_PIN != NRF_QSPI_PIN_NOT_CONNECTED &&
                 MOTA_QSPI_IO0_PIN != NRF_QSPI_PIN_NOT_CONNECTED &&
                 MOTA_QSPI_IO1_PIN != NRF_QSPI_PIN_NOT_CONNECTED,
               "QSPI SCK, CSN, IO0, and IO1 pins must be connected");
#if defined(MOTA_QSPI_AUX_CSN_PIN)
_Static_assert(MOTA_QSPI_AUX_CSN_PIN != NRF_QSPI_PIN_NOT_CONNECTED &&
                 MOTA_QSPI_AUX_CSN_PIN != MOTA_QSPI_SCK_PIN &&
                 MOTA_QSPI_AUX_CSN_PIN != MOTA_QSPI_CSN_PIN &&
                 MOTA_QSPI_AUX_CSN_PIN != MOTA_QSPI_IO0_PIN &&
                 MOTA_QSPI_AUX_CSN_PIN != MOTA_QSPI_IO1_PIN &&
                 MOTA_QSPI_AUX_CSN_PIN != MOTA_QSPI_IO2_PIN &&
                 MOTA_QSPI_AUX_CSN_PIN != MOTA_QSPI_IO3_PIN,
               "QSPI auxiliary CSN must be connected and distinct from the flash bus pins");
#endif

static void feed_watchdogs(void) {
  otafix_watchdog_feed();
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
  nrf_qspi_cinstr_conf_t config = {
    .opcode = opcode,
    .length = length,
    .io2_level = true,
    .io3_level = true,
  };
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

static __attribute__((noinline)) bool wait_memory_ready(uint32_t max_steps) {
  uint8_t status[4] __attribute__((aligned(4))) = {0, 0, 0, 0};
  for (uint32_t step = 0; step < max_steps; step++) {
    if (!custom_instruction(QSPI_READ_STATUS, NRF_QSPI_CINSTR_LEN_2B, status)) {
      return false;
    }
    if ((status[0] & QSPI_STATUS_WIP) == 0) {
      return true;
    }
    if ((step & 0x3Fu) == 0) {
      feed_watchdogs();
    }
    nrf_delay_us(QSPI_PROGRAM_WAIT_STEP_US);
  }
  return false;
}

#if defined(MOTA_QSPI_AUX_CSN_PIN)
static void deselect_aux_device(void) {
  // Preload high before changing direction so an active-low device sharing
  // SCK/IO0/IO1 never observes a select pulse during flash initialization.
  QSPI_GPIO_PORT(MOTA_QSPI_AUX_CSN_PIN)->OUTSET =
    1u << QSPI_GPIO_INDEX(MOTA_QSPI_AUX_CSN_PIN);
  QSPI_GPIO_PORT(MOTA_QSPI_AUX_CSN_PIN)->PIN_CNF[QSPI_GPIO_INDEX(MOTA_QSPI_AUX_CSN_PIN)] =
    QSPI_PIN_CNF_OUTPUT_H0H1;
}
#endif

static void configure_qspi_pins(bool enable) {
  const uint32_t pin_cnf = enable ? QSPI_PIN_CNF_H0H1 : QSPI_PIN_CNF_DEFAULT;
  if (enable) {
    // Preload benign SPI mode-0 levels before PSEL gives QSPI ownership.
    QSPI_GPIO_PORT(MOTA_QSPI_CSN_PIN)->OUTSET = 1u << QSPI_GPIO_INDEX(MOTA_QSPI_CSN_PIN);
    QSPI_GPIO_PORT(MOTA_QSPI_SCK_PIN)->OUTCLR = 1u << QSPI_GPIO_INDEX(MOTA_QSPI_SCK_PIN);
  }
  // Match current nrfx: QSPI owns direction while active; connected pads
  // remain GPIO inputs with disconnected input buffers and H0H1 drive.
  QSPI_GPIO_PORT(MOTA_QSPI_SCK_PIN)->PIN_CNF[QSPI_GPIO_INDEX(MOTA_QSPI_SCK_PIN)] = pin_cnf;
  QSPI_GPIO_PORT(MOTA_QSPI_CSN_PIN)->PIN_CNF[QSPI_GPIO_INDEX(MOTA_QSPI_CSN_PIN)] = pin_cnf;
  QSPI_GPIO_PORT(MOTA_QSPI_IO0_PIN)->PIN_CNF[QSPI_GPIO_INDEX(MOTA_QSPI_IO0_PIN)] = pin_cnf;
  QSPI_GPIO_PORT(MOTA_QSPI_IO1_PIN)->PIN_CNF[QSPI_GPIO_INDEX(MOTA_QSPI_IO1_PIN)] = pin_cnf;
  if (MOTA_QSPI_IO2_PIN != NRF_QSPI_PIN_NOT_CONNECTED) {
    QSPI_GPIO_PORT(MOTA_QSPI_IO2_PIN)->PIN_CNF[QSPI_GPIO_INDEX(MOTA_QSPI_IO2_PIN)] = pin_cnf;
  }
  if (MOTA_QSPI_IO3_PIN != NRF_QSPI_PIN_NOT_CONNECTED) {
    QSPI_GPIO_PORT(MOTA_QSPI_IO3_PIN)->PIN_CNF[QSPI_GPIO_INDEX(MOTA_QSPI_IO3_PIN)] = pin_cnf;
  }
}

static void wake_flash_gpio(void) {
  // QSPI ACTIVATE itself talks to the NOR and never becomes READY if a prior
  // probe left the chip in deep power-down.  Send 0xAB as slow mode-0 GPIO SPI
  // first.  Preloading every output avoids a CS# pulse or clock edge while
  // GPIO ownership is established.  IO1 stays an input; connected IO2/IO3 are
  // held high so WP#/HOLD# remain inactive during the single-line command.
  QSPI_GPIO_PORT(MOTA_QSPI_CSN_PIN)->OUTSET = 1u << QSPI_GPIO_INDEX(MOTA_QSPI_CSN_PIN);
  QSPI_GPIO_PORT(MOTA_QSPI_SCK_PIN)->OUTCLR = 1u << QSPI_GPIO_INDEX(MOTA_QSPI_SCK_PIN);
  QSPI_GPIO_PORT(MOTA_QSPI_IO0_PIN)->OUTSET = 1u << QSPI_GPIO_INDEX(MOTA_QSPI_IO0_PIN);
  QSPI_GPIO_PORT(MOTA_QSPI_CSN_PIN)->PIN_CNF[QSPI_GPIO_INDEX(MOTA_QSPI_CSN_PIN)] = QSPI_PIN_CNF_OUTPUT_H0H1;
  QSPI_GPIO_PORT(MOTA_QSPI_SCK_PIN)->PIN_CNF[QSPI_GPIO_INDEX(MOTA_QSPI_SCK_PIN)] = QSPI_PIN_CNF_OUTPUT_H0H1;
  QSPI_GPIO_PORT(MOTA_QSPI_IO0_PIN)->PIN_CNF[QSPI_GPIO_INDEX(MOTA_QSPI_IO0_PIN)] = QSPI_PIN_CNF_OUTPUT_H0H1;
  QSPI_GPIO_PORT(MOTA_QSPI_IO1_PIN)->PIN_CNF[QSPI_GPIO_INDEX(MOTA_QSPI_IO1_PIN)] = QSPI_PIN_CNF_H0H1;
  if (MOTA_QSPI_IO2_PIN != NRF_QSPI_PIN_NOT_CONNECTED) {
    QSPI_GPIO_PORT(MOTA_QSPI_IO2_PIN)->OUTSET = 1u << QSPI_GPIO_INDEX(MOTA_QSPI_IO2_PIN);
    QSPI_GPIO_PORT(MOTA_QSPI_IO2_PIN)->PIN_CNF[QSPI_GPIO_INDEX(MOTA_QSPI_IO2_PIN)] = QSPI_PIN_CNF_OUTPUT_H0H1;
  }
  if (MOTA_QSPI_IO3_PIN != NRF_QSPI_PIN_NOT_CONNECTED) {
    QSPI_GPIO_PORT(MOTA_QSPI_IO3_PIN)->OUTSET = 1u << QSPI_GPIO_INDEX(MOTA_QSPI_IO3_PIN);
    QSPI_GPIO_PORT(MOTA_QSPI_IO3_PIN)->PIN_CNF[QSPI_GPIO_INDEX(MOTA_QSPI_IO3_PIN)] = QSPI_PIN_CNF_OUTPUT_H0H1;
  }

  nrf_delay_us(OTA_QSPI_WAKE_GUARD_US);
  QSPI_GPIO_PORT(MOTA_QSPI_CSN_PIN)->OUTCLR = 1u << QSPI_GPIO_INDEX(MOTA_QSPI_CSN_PIN);
  for (uint8_t bit = 0; bit < OTA_QSPI_WAKE_BITS; bit++) {
    if (ota_qspi_wake_bit(bit)) {
      QSPI_GPIO_PORT(MOTA_QSPI_IO0_PIN)->OUTSET = 1u << QSPI_GPIO_INDEX(MOTA_QSPI_IO0_PIN);
    } else {
      QSPI_GPIO_PORT(MOTA_QSPI_IO0_PIN)->OUTCLR = 1u << QSPI_GPIO_INDEX(MOTA_QSPI_IO0_PIN);
    }
    nrf_delay_us(OTA_QSPI_WAKE_EDGE_US);
    QSPI_GPIO_PORT(MOTA_QSPI_SCK_PIN)->OUTSET = 1u << QSPI_GPIO_INDEX(MOTA_QSPI_SCK_PIN);
    nrf_delay_us(OTA_QSPI_WAKE_EDGE_US);
    QSPI_GPIO_PORT(MOTA_QSPI_SCK_PIN)->OUTCLR = 1u << QSPI_GPIO_INDEX(MOTA_QSPI_SCK_PIN);
    nrf_delay_us(OTA_QSPI_WAKE_EDGE_US);
  }
  QSPI_GPIO_PORT(MOTA_QSPI_CSN_PIN)->OUTSET = 1u << QSPI_GPIO_INDEX(MOTA_QSPI_CSN_PIN);
  nrf_delay_us(OTA_QSPI_WAKE_GUARD_US);

  // Restore the exact nrfx QSPI pad configuration before assigning PSEL.
  configure_qspi_pins(true);
}

static void select_qspi_pins(bool enable) {
  const uint32_t off = NRF_QSPI_PIN_VAL(NRF_QSPI_PIN_NOT_CONNECTED);
  NRF_QSPI->PSEL.SCK = enable ? NRF_QSPI_PIN_VAL(MOTA_QSPI_SCK_PIN) : off;
  NRF_QSPI->PSEL.CSN = enable ? NRF_QSPI_PIN_VAL(MOTA_QSPI_CSN_PIN) : off;
  NRF_QSPI->PSEL.IO0 = enable ? NRF_QSPI_PIN_VAL(MOTA_QSPI_IO0_PIN) : off;
  NRF_QSPI->PSEL.IO1 = enable ? NRF_QSPI_PIN_VAL(MOTA_QSPI_IO1_PIN) : off;
  NRF_QSPI->PSEL.IO2 = enable ? NRF_QSPI_PIN_VAL(MOTA_QSPI_IO2_PIN) : off;
  NRF_QSPI->PSEL.IO3 = enable ? NRF_QSPI_PIN_VAL(MOTA_QSPI_IO3_PIN) : off;
}

bool ota_qspi_init(void) {
  #if defined(MOTA_QSPI_AUX_CSN_PIN)
  // Keep the other active-low SPI device deselected before any wake clocks or
  // QSPI peripheral activity. Leave it driven high until the application
  // deliberately reconfigures its radio after handoff.
  deselect_aux_device();
  #endif
  if (g_capacity != 0) {
    return true;
  }
  g_capacity = 0;
  g_awake = false;

  #if defined(MOTA_QSPI_POWER_PIN)
  nrf_gpio_cfg_output(MOTA_QSPI_POWER_PIN);
  nrf_gpio_pin_write(MOTA_QSPI_POWER_PIN, MOTA_QSPI_POWER_ACTIVE);
  nrf_delay_ms(2);
  #endif

  nrf_qspi_int_disable(NRF_QSPI, 0xFFFFFFFFu);
  NVIC_DisableIRQ(QSPI_IRQn);
  NVIC_ClearPendingIRQ(QSPI_IRQn);

  wake_flash_gpio();
  // From this point onward the NOR may be awake or completing an operation
  // interrupted by reset.  Even if ACTIVATE times out, deinit must not remove
  // its rail until SR1 proves WIP clear and deep power-down succeeds.
  g_awake = true;
  select_qspi_pins(true);

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
  if (!wait_memory_ready(QSPI_RECOVERY_WAIT_STEPS)) {
    ota_qspi_deinit();
    return false;
  }

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
  return true;
}

void ota_qspi_deinit(void) {
  if (!g_active) {
    return;
  }
  bool flash_released = !g_awake;
  if (g_awake) {
    // The application may run immediately after a rejected handoff without a
    // reset. Balance every completed 0xAB wake with deep power-down, including
    // a later JEDEC validation failure. Never sleep or remove power while an
    // interrupted application program/erase is still in progress.
    if (wait_memory_ready(QSPI_RECOVERY_WAIT_STEPS) &&
        custom_instruction(QSPI_DPD_ENTER, NRF_QSPI_CINSTR_LEN_1B, NULL)) {
      nrf_delay_us(QSPI_DPD_RELEASE_GUARD_US);
      flash_released = true;
    }
  }
  g_awake = false;
  nrf_qspi_event_clear(NRF_QSPI, NRF_QSPI_EVENT_READY);
  nrf_qspi_task_trigger(NRF_QSPI, NRF_QSPI_TASK_DEACTIVATE);
  nrf_qspi_disable(NRF_QSPI);
  nrf_qspi_event_clear(NRF_QSPI, NRF_QSPI_EVENT_READY);
  g_active = false;
  select_qspi_pins(false);
  configure_qspi_pins(false);
  if (!flash_released) {
    // If status could not prove the NOR idle, keep CS# asserted high even
    // after releasing the QSPI peripheral. This lets an in-flight internal
    // operation finish safely without relying on a board-level pull-up.
    QSPI_GPIO_PORT(MOTA_QSPI_CSN_PIN)->OUTSET = 1u << QSPI_GPIO_INDEX(MOTA_QSPI_CSN_PIN);
    QSPI_GPIO_PORT(MOTA_QSPI_CSN_PIN)->PIN_CNF[QSPI_GPIO_INDEX(MOTA_QSPI_CSN_PIN)] = QSPI_PIN_CNF_OUTPUT_H0H1;
  }
  g_capacity = 0;

  #if defined(MOTA_QSPI_POWER_PIN)
  if (flash_released) {
    nrf_gpio_pin_write(MOTA_QSPI_POWER_PIN, MOTA_QSPI_POWER_ACTIVE ? 0u : 1u);
  }
  #endif
}

uint32_t ota_qspi_capacity(void) {
  return g_capacity;
}

static bool read_aligned(uint32_t offset, uint8_t *dst, uint32_t len) {
  if ((offset & (OTA_QSPI_DMA_ALIGNMENT - 1u)) != 0 ||
      ((uintptr_t)dst & (OTA_QSPI_DMA_ALIGNMENT - 1u)) != 0 ||
      (len & (OTA_QSPI_DMA_ALIGNMENT - 1u)) != 0 || len == 0 ||
      offset > g_capacity || len > g_capacity - offset) {
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
      len > 256u - (offset & 255u) || offset > g_capacity || len > g_capacity - offset) {
    return false;
  }
  nrf_qspi_write_buffer_set(NRF_QSPI, src, len, offset);
  nrf_qspi_event_clear(NRF_QSPI, NRF_QSPI_EVENT_READY);
  nrf_qspi_task_trigger(NRF_QSPI, NRF_QSPI_TASK_WRITESTART);
  return wait_ready() && wait_memory_ready(QSPI_PROGRAM_WAIT_STEPS);
}

bool ota_qspi_read(uint32_t offset, void *dst, uint32_t len) {
  if (g_capacity == 0 || dst == NULL || offset > g_capacity || len > g_capacity - offset) {
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
  if (g_capacity == 0 || src == NULL || len != QSPI_APPROVAL_LEN || (offset & 255u) + len > 256u ||
      offset > g_capacity || len > g_capacity - offset) {
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
