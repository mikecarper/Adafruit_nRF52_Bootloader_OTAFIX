#ifndef _WISCORE_RAK3401_RAK13302_W25Q16_H
#define _WISCORE_RAK3401_RAK13302_W25Q16_H

#include "../wiscore_rak3401/board.h"

// This is the same physical RAK3401 core and intentionally retains its legacy
// USB VID/PID. The distinct DEVICE_NAME and UF2 board ID bind updates to this
// external-flash configuration.

// W25Q16JV on the SPI bus shared with the RAK13302 1 W radio. The flash has
// its own CS on P0.31; P0.26 is the radio's active-low NSS and must remain
// deasserted throughout every flash transaction. This mapping leaves the
// Slot A GPS UART/PPS pins untouched.
#define MOTA_QSPI_SCK_PIN     _PINNUM(0, 3)
#define MOTA_QSPI_CSN_PIN     _PINNUM(0, 31)
#define MOTA_QSPI_IO0_PIN     _PINNUM(0, 30) // MOSI / breakout DI
#define MOTA_QSPI_IO1_PIN     _PINNUM(0, 29) // MISO / breakout DO
#define MOTA_QSPI_IO2_PIN     0xFFu           // not connected; breakout holds WP# high
#define MOTA_QSPI_IO3_PIN     0xFFu           // not connected; breakout holds HOLD# high
#define MOTA_QSPI_AUX_CSN_PIN _PINNUM(0, 26) // RAK13302 NSS; drive high before bus activity
#define MOTA_QSPI_SCK_FREQ    NRF_QSPI_FREQ_32MDIV4 // conservative 8 MHz

// Require the exact 2 MiB Winbond W25Q16JV JEDEC signature. A missing or
// different device on this shared bus must not be mistaken for the OTA store.
#define MOTA_QSPI_JEDEC_MANUFACTURER 0xEFu
#define MOTA_QSPI_JEDEC_MEMORY_TYPE  0x40u
#define MOTA_QSPI_JEDEC_CAPACITY     0x15u

#undef BLEDIS_MODEL
#define BLEDIS_MODEL "RAK3401 + RAK13302 + W25Q16"

#undef UF2_PRODUCT_NAME
#undef UF2_VOLUME_LABEL
#undef UF2_BOARD_ID
#undef UF2_INDEX_URL
#define UF2_PRODUCT_NAME "WisBlock RAK3401 + RAK13302 + W25Q16"
#define UF2_VOLUME_LABEL "3401W25Q16"
#define UF2_BOARD_ID     "WisBlock-RAK3401-RAK13302-W25Q16"
#define UF2_INDEX_URL    "https://docs.rakwireless.com/product-categories/wisblock/rak3401/overview/"

#endif // _WISCORE_RAK3401_RAK13302_W25Q16_H
