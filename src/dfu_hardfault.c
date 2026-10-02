#include <stddef.h>

#include "dfu_entry.h"
#include "nrf.h"
#include "system_reset.h"

_Static_assert(SCB_BASE + offsetof(SCB_Type, AIRCR) == 0xE000ED0C, "unexpected ARM AIRCR address");
_Static_assert(SCB_AIRCR_PRIGROUP_Msk == 0x700 && SCB_AIRCR_SYSRESETREQ_Msk == 4 && SCB_AIRCR_VECTKEY_Pos == 16,
               "unexpected ARM reset encoding");

// Match CMSIS NVIC_SystemReset, including PRIGROUP and both barriers, without
// using a stack. The fault handler shares this sequence with ordinary resets.
__attribute__((naked, noinline, noreturn, section(".text.otafix_reset"))) void otafix_system_reset(void) {
  __asm volatile("dsb\n"
                 "ldr r1, =0xE000ED0C\n"
                 "ldr r0, [r1]\n"
                 "and r0, r0, #0x700\n"
                 "ldr r2, =0x05FA0004\n"
                 "orrs r0, r2\n"
                 "str r0, [r1]\n"
                 "dsb\n"
                 "1: b 1b\n");
}

#if defined(NRF52) || defined(NRF52832_XXAA) || defined(NRF52833_XXAA) || defined(NRF52840_XXAA)

// The assembly cannot use a C frame: a legacy BLEDfu callback can enter with
// MSP already beyond RAM after selecting it before restoring its PSP frame.
// Keep these fixed MMIO addresses and constants tied to the Nordic/CMSIS ABI.
_Static_assert(NRF_POWER_BASE + offsetof(NRF_POWER_Type, GPREGRET) == 0x4000051C, "unexpected nRF52 GPREGRET address");
_Static_assert(sizeof(NRF_POWER->GPREGRET) == 4, "GPREGRET requires word MMIO");
_Static_assert(DFU_MAGIC_OTA_APPJUM == 0xB1 && DFU_MAGIC_OTA_RESET == 0xA8, "unexpected BLE DFU entry magic");

// The shared section keeps the branch to the reset sequence in 16-bit range.
__attribute__((naked, noreturn, section(".text.otafix_reset"))) void HardFault_Handler(void) {
  __asm volatile("ldr r1, =0x4000051C\n"
                 "ldr r0, [r1]\n"
                 "cmp r0, #0xB1\n"
                 "bne 1f\n"
                 "movs r0, #0xA8\n"
                 "str r0, [r1]\n"
                 "b.n otafix_system_reset\n"
                 "1: b 1b\n");
}

#endif
