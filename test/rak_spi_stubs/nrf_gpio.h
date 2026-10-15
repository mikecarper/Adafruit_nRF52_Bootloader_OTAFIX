#ifndef RAK_SPI_TEST_GPIO_H
#define RAK_SPI_TEST_GPIO_H
#include <stdint.h>
#define NRF_GPIO_PIN_PULLUP 3u
#ifdef __cplusplus
extern "C" {
#endif
void nrf_gpio_pin_set(uint32_t pin);
void nrf_gpio_pin_clear(uint32_t pin);
void nrf_gpio_cfg_output(uint32_t pin);
void nrf_gpio_cfg_input(uint32_t pin, uint32_t pull);
void nrf_gpio_cfg_default(uint32_t pin);
#ifdef __cplusplus
}
#endif
#endif
