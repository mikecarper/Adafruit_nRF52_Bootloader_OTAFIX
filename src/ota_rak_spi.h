// Shared single-line SPIM2 transport for the exact combined RAK4631 profile.
// The authenticated apply selector chooses one device before any bus access.
#ifndef OTA_RAK_SPI_H_
#define OTA_RAK_SPI_H_

#include <stdbool.h>
#include <stdint.h>

bool ota_rak_spi_begin(uint8_t cs, uint8_t sck, uint8_t mosi, uint8_t miso, uint32_t frequency);
void ota_rak_spi_set_frequency(uint32_t frequency);
void ota_rak_spi_select(bool selected);
bool ota_rak_spi_transfer(const void *tx, void *rx, uint32_t length);
uint8_t ota_rak_spi_byte(uint8_t value);
bool ota_rak_spi_healthy(void);
void ota_rak_spi_release(bool keep_cs_high);
void ota_rak_spi_watchdog(void);

#endif // OTA_RAK_SPI_H_
