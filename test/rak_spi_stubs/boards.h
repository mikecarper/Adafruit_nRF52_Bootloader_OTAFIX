#ifndef RAK_SPI_TEST_BOARDS_H
#define RAK_SPI_TEST_BOARDS_H
#define MOTA_SD_CS_PIN 26u
#define MOTA_SD_SCK_PIN 3u
#define MOTA_SD_MOSI_PIN 30u
#define MOTA_SD_MISO_PIN 29u
#define MOTA_QSPI_CSN_PIN 31u
#ifdef __cplusplus
extern "C" {
#endif
void board_watchdog_feed(void);
#ifdef __cplusplus
}
#endif
#endif
