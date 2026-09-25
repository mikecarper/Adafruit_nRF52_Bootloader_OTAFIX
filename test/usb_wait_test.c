#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "usb_wait.h"

_Static_assert(DFU_USB_ENUMERATION_TIMEOUT_MS == 30000u,
               "the default no-image USB enumeration grace period must be 30 seconds");
_Static_assert(DFU_USB_VBUS_SETTLE_MS == 3000u,
               "cold USB power-up must get a bounded VBUS settle interval");

static uint32_t now_ms;
static uint32_t mount_at_ms;
static uint32_t vbus_arrive_at_ms;
static uint32_t remove_vbus_at_ms;
static uint32_t task_calls;
static uint32_t watchdog_calls;
static uint32_t delay_calls;

bool usb_wait_vbus_present(void) {
  return now_ms >= vbus_arrive_at_ms && now_ms < remove_vbus_at_ms;
}

void usb_wait_task(void) {
  task_calls++;
}

bool usb_wait_mounted(void) {
  return now_ms >= mount_at_ms;
}

void usb_wait_feed_watchdog(void) {
  watchdog_calls++;
}

void usb_wait_delay_ms(uint32_t delay_ms) {
  now_ms += delay_ms;
  delay_calls++;
}

static void reset_probe(uint32_t mount_ms, uint32_t vbus_remove_ms) {
  now_ms            = 0;
  mount_at_ms       = mount_ms;
  vbus_arrive_at_ms = 0;
  remove_vbus_at_ms = vbus_remove_ms;
  task_calls        = 0;
  watchdog_calls    = 0;
  delay_calls       = 0;
}

static int expect(bool condition, const char *message) {
  if (!condition) {
    fprintf(stderr, "FAIL: %s\n", message);
    return 1;
  }
  return 0;
}

int main(void) {
  int failures = 0;

  printf("[1] deliberate serial-only entry gets 30 seconds: ");
  failures += expect(dfu_buttonless_timeout_ms(true, false) ==
                         DFU_USB_ENUMERATION_TIMEOUT_MS,
                     "0x4E/1200-touch entry must use the full configured USB window");
  printf("%s\n", failures ? "FAIL" : "PASS");

  printf("[2] deliberate UF2 entry gets 30 seconds: ");
  int before = failures;
  failures += expect(dfu_buttonless_timeout_ms(false, true) ==
                         DFU_USB_ENUMERATION_TIMEOUT_MS,
                     "0x57 UF2 entry must use the full configured USB window");
  printf("%s\n", failures == before ? "PASS" : "FAIL");

  printf("[3] both explicit entry flags still get the full window: ");
  before = failures;
  failures += expect(dfu_buttonless_timeout_ms(true, true) ==
                         DFU_USB_ENUMERATION_TIMEOUT_MS,
                     "simultaneous explicit flags must retain the full configured USB window");
  printf("%s\n", failures == before ? "PASS" : "FAIL");

  printf("[4] single-tap recovery remains three seconds: ");
  before = failures;
  failures += expect(dfu_buttonless_timeout_ms(false, false) ==
                         DFU_SINGLE_TAP_TIMEOUT_MS &&
                         DFU_SINGLE_TAP_TIMEOUT_MS == 3000u,
                     "single-tap recovery must retain its brief three-second window");
  printf("%s\n", failures == before ? "PASS" : "FAIL");

  printf("[5] battery-only recovery has a bounded VBUS settle wait: ");
  reset_probe(UINT32_MAX, 0);
  bool mounted = usb_wait_for_mount(DFU_USB_ENUMERATION_TIMEOUT_MS);
  failures += expect(!mounted && now_ms == DFU_USB_VBUS_SETTLE_MS &&
                         task_calls == DFU_USB_VBUS_SETTLE_MS + 1u &&
                         watchdog_calls == DFU_USB_VBUS_SETTLE_MS &&
                         delay_calls == DFU_USB_VBUS_SETTLE_MS,
                     "battery-only recovery must fall back after a bounded, serviced settle wait");
  printf("%s\n", failures ? "FAIL" : "PASS");

  printf("[6] VBUS appearing after CPU startup still reaches USB recovery: ");
  before = failures;
  reset_probe(120u, UINT32_MAX);
  vbus_arrive_at_ms = 37u;
  mounted = usb_wait_for_mount(DFU_USB_ENUMERATION_TIMEOUT_MS);
  failures += expect(mounted && now_ms == 120u && delay_calls == 120u,
                     "late VBUS must not cause an immediate BLE fallback");
  printf("%s\n", failures == before ? "PASS" : "FAIL");

  printf("[7] delayed host enumeration within 30 seconds succeeds: ");
  before = failures;
  reset_probe(29999u, UINT32_MAX);
  mounted = usb_wait_for_mount(DFU_USB_ENUMERATION_TIMEOUT_MS);
  failures += expect(mounted && now_ms == 29999u && delay_calls == 29999u,
                     "a host mounted just before the deadline must keep USB DFU active");
  printf("%s\n", failures == before ? "PASS" : "FAIL");

  printf("[8] enumeration exactly at the deadline succeeds: ");
  before = failures;
  reset_probe(DFU_USB_ENUMERATION_TIMEOUT_MS, UINT32_MAX);
  mounted = usb_wait_for_mount(DFU_USB_ENUMERATION_TIMEOUT_MS);
  failures += expect(mounted && now_ms == DFU_USB_ENUMERATION_TIMEOUT_MS &&
                         task_calls == DFU_USB_ENUMERATION_TIMEOUT_MS + 1u,
                     "the final TinyUSB poll must accept a host mounted at the deadline");
  printf("%s\n", failures == before ? "PASS" : "FAIL");

  printf("[9] powered USB without a data host falls back after 30 seconds: ");
  before = failures;
  reset_probe(UINT32_MAX, UINT32_MAX);
  mounted = usb_wait_for_mount(DFU_USB_ENUMERATION_TIMEOUT_MS);
  failures += expect(!mounted && now_ms == DFU_USB_ENUMERATION_TIMEOUT_MS &&
                         watchdog_calls == DFU_USB_ENUMERATION_TIMEOUT_MS,
                     "VBUS without enumeration must use the complete grace period then fall back");
  printf("%s\n", failures == before ? "PASS" : "FAIL");

  printf("[10] VBUS removal beats a stale mounted flag within the settle window: ");
  before = failures;
  // Model a stale TinyUSB mounted flag at the same instant VBUS disappears.
  // Physical power removal must win so recovery cannot remain in dead USB DFU.
  reset_probe(17u, 17u);
  mounted = usb_wait_for_mount(DFU_USB_ENUMERATION_TIMEOUT_MS);
  failures += expect(!mounted && now_ms == DFU_USB_VBUS_SETTLE_MS &&
                         delay_calls == DFU_USB_VBUS_SETTLE_MS,
                     "VBUS removal must beat a stale mounted flag and fall back within three seconds");
  printf("%s\n", failures == before ? "PASS" : "FAIL");

  printf("[11] VBUS removal beats a stale mounted flag at the deadline: ");
  before = failures;
  reset_probe(DFU_USB_ENUMERATION_TIMEOUT_MS, DFU_USB_ENUMERATION_TIMEOUT_MS);
  mounted = usb_wait_for_mount(DFU_USB_ENUMERATION_TIMEOUT_MS);
  failures += expect(!mounted && now_ms == DFU_USB_ENUMERATION_TIMEOUT_MS &&
                         task_calls == DFU_USB_ENUMERATION_TIMEOUT_MS + 1u,
                     "the final deadline poll must require live VBUS before accepting mounted");
  printf("%s\n", failures == before ? "PASS" : "FAIL");

  printf("[12] VBUS arriving after the settle window cannot keep USB active: ");
  before = failures;
  reset_probe(DFU_USB_VBUS_SETTLE_MS + 5u, UINT32_MAX);
  vbus_arrive_at_ms = DFU_USB_VBUS_SETTLE_MS + 1u;
  mounted = usb_wait_for_mount(DFU_USB_ENUMERATION_TIMEOUT_MS);
  failures += expect(!mounted && now_ms == DFU_USB_VBUS_SETTLE_MS,
                     "a later cable connection needs a fresh DFU entry");
  printf("%s\n", failures == before ? "PASS" : "FAIL");

  printf("\n%s (%d failure%s)\n", failures ? "SUITE FAILED" : "SUITE PASSED", failures,
         failures == 1 ? "" : "s");
  return failures ? 1 : 0;
}
