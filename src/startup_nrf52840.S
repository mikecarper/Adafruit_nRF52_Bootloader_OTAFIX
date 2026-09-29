/*
 * Copyright (c) 2009-2018 ARM Limited. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 * Vector entries derived from Nordic's gcc_startup_nrf52840.S.
 *
 * Keep the vendor reset routine, stack declarations and weak handlers. Its
 * unused 512-byte vector section is renamed so --gc-sections discards it.
 * nRF52840 implements IRQs 0..47; the complete table is 16 + 48 words.
 * BOOTLOADER_REGION_START still provides at least 512-byte VTOR alignment.
 */
    .syntax unified
    .arch armv7e-m

    .section .isr_vector, "a", %progbits
    .align 2
    .globl __isr_vector
__isr_vector:
    .long   __StackTop                  /* Top of Stack */
    .long   Reset_Handler
    .long   NMI_Handler
    .long   HardFault_Handler
    .long   MemoryManagement_Handler
    .long   BusFault_Handler
    .long   UsageFault_Handler
    .long   0                           /*Reserved */
    .long   0                           /*Reserved */
    .long   0                           /*Reserved */
    .long   0                           /*Reserved */
    .long   SVC_Handler
    .long   DebugMon_Handler
    .long   0                           /*Reserved */
    .long   PendSV_Handler
    .long   SysTick_Handler

  /* External Interrupts */
    .long   POWER_CLOCK_IRQHandler
    .long   RADIO_IRQHandler
    .long   UARTE0_UART0_IRQHandler
    .long   SPIM0_SPIS0_TWIM0_TWIS0_SPI0_TWI0_IRQHandler
    .long   SPIM1_SPIS1_TWIM1_TWIS1_SPI1_TWI1_IRQHandler
    .long   NFCT_IRQHandler
    .long   GPIOTE_IRQHandler
    .long   SAADC_IRQHandler
    .long   TIMER0_IRQHandler
    .long   TIMER1_IRQHandler
    .long   TIMER2_IRQHandler
    .long   RTC0_IRQHandler
    .long   TEMP_IRQHandler
    .long   RNG_IRQHandler
    .long   ECB_IRQHandler
    .long   CCM_AAR_IRQHandler
    .long   WDT_IRQHandler
    .long   RTC1_IRQHandler
    .long   QDEC_IRQHandler
    .long   COMP_LPCOMP_IRQHandler
    .long   SWI0_EGU0_IRQHandler
    .long   SWI1_EGU1_IRQHandler
    .long   SWI2_EGU2_IRQHandler
    .long   SWI3_EGU3_IRQHandler
    .long   SWI4_EGU4_IRQHandler
    .long   SWI5_EGU5_IRQHandler
    .long   TIMER3_IRQHandler
    .long   TIMER4_IRQHandler
    .long   PWM0_IRQHandler
    .long   PDM_IRQHandler
    .long   0                           /*Reserved */
    .long   0                           /*Reserved */
    .long   MWU_IRQHandler
    .long   PWM1_IRQHandler
    .long   PWM2_IRQHandler
    .long   SPIM2_SPIS2_SPI2_IRQHandler
    .long   RTC2_IRQHandler
    .long   I2S_IRQHandler
    .long   FPU_IRQHandler
    .long   USBD_IRQHandler
    .long   UARTE1_IRQHandler
    .long   QSPI_IRQHandler
    .long   CRYPTOCELL_IRQHandler
    .long   0                           /*Reserved */
    .long   0                           /*Reserved */
    .long   PWM3_IRQHandler
    .long   0                           /*Reserved */
    .long   SPIM3_IRQHandler
    .size __isr_vector, . - __isr_vector

#define isr_vector otafix_unused_sdk_vectors
#define __isr_vector __otafix_unused_sdk_vectors
#include "../lib/nrfx/mdk/gcc_startup_nrf52840.S"
#undef __isr_vector
#undef isr_vector

