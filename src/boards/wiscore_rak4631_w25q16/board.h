#ifndef _WISCORE_RAK4631_W25Q16_H
#define _WISCORE_RAK4631_W25Q16_H

#include "../wiscore_rak4631_board/board.h"

// This is the same physical RAK4631 core and intentionally retains its legacy
// USB VID/PID. The distinct DEVICE_NAME and UF2 board ID bind updates to this
// external-flash configuration.

// W25Q16JV on the WisBlock SPI signals with a dedicated CS on P0.31. The
// RAK4631's internal LoRa radio uses a separate SPI bus, so this target does
// not need the RAK3401/RAK13302 auxiliary-CS guard. The mapping leaves the
// Slot A GPS UART/PPS pins untouched.
#define MOTA_QSPI_SCK_PIN _PINNUM(0, 3)
#define MOTA_QSPI_CSN_PIN _PINNUM(0, 31)
#define MOTA_QSPI_IO0_PIN _PINNUM(0, 30) // MOSI / breakout DI
#define MOTA_QSPI_IO1_PIN _PINNUM(0, 29) // MISO / breakout DO
#define MOTA_QSPI_IO2_PIN 0xFFu           // not connected; breakout holds WP# high
#define MOTA_QSPI_IO3_PIN 0xFFu           // not connected; breakout holds HOLD# high
#define MOTA_QSPI_SCK_FREQ NRF_QSPI_FREQ_32MDIV4 // conservative 8 MHz

// Require the exact 2 MiB Winbond W25Q16JV JEDEC signature. A missing or
// different device must not be mistaken for the OTA staging store.
#define MOTA_QSPI_JEDEC_MANUFACTURER 0xEFu
#define MOTA_QSPI_JEDEC_MEMORY_TYPE  0x40u
#define MOTA_QSPI_JEDEC_CAPACITY     0x15u

#undef BLEDIS_MODEL
#define BLEDIS_MODEL "RAK4631 + W25Q16"

#undef UF2_PRODUCT_NAME
#undef UF2_VOLUME_LABEL
#undef UF2_BOARD_ID
#undef UF2_INDEX_URL
#define UF2_PRODUCT_NAME "WisBlock RAK4631 + W25Q16"
#define UF2_VOLUME_LABEL "4631W25Q16"
#define UF2_BOARD_ID     "WisBlock-RAK4631-W25Q16"
#define UF2_INDEX_URL    "https://docs.rakwireless.com/product-categories/wisblock/rak4631/overview/"

#endif // _WISCORE_RAK4631_W25Q16_H
