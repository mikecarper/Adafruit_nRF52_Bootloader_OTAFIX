#ifndef RAK_SPI_TEST_DELAY_H
#define RAK_SPI_TEST_DELAY_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
void nrf_delay_us(uint32_t value);
void nrf_delay_ms(uint32_t value);
#ifdef __cplusplus
}
#endif
#endif
