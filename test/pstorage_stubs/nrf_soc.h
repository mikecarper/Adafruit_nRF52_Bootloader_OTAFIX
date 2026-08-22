#ifndef NRF_SOC_H
#define NRF_SOC_H

#include <stdint.h>

#define NRF_EVT_FLASH_OPERATION_SUCCESS 1u
#define NRF_EVT_FLASH_OPERATION_ERROR   2u

uint32_t sd_flash_write(uint32_t * dst, uint32_t const * src, uint32_t size);
uint32_t sd_flash_page_erase(uint32_t page_number);

#endif
