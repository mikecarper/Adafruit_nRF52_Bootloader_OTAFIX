#pragma once

// Share the CMSIS-equivalent reset sequence, preserving the priority group.
// Its assembly requires no stack, so the narrow DFU fault recovery can branch
// directly here even if the application has left MSP beyond physical RAM.
__attribute__((noreturn)) void otafix_system_reset(void);
