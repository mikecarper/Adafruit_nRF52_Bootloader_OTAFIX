#ifndef _WISCORE_RAK4631_AUTO_H
#define _WISCORE_RAK4631_AUTO_H

#include "../wiscore_rak4631_board/board.h"

// RAK15001 Slot C uses the WisBlock SPI bus. A header-wired W25Q16 uses
// TX1/RX1/IO1 for its bus; both layouts have distinct handoff markers.
#define MOTA_RAK_AUTO_STORE 1
#define MOTA_RAK_AUTO_RAK4631 1
#define MOTA_QSPI_SCK_PIN _PINNUM(0, 3)
#define MOTA_QSPI_CSN_PIN _PINNUM(0, 31)
#define MOTA_QSPI_IO0_PIN _PINNUM(0, 30)
#define MOTA_QSPI_IO1_PIN _PINNUM(0, 29)
#define MOTA_QSPI_IO2_PIN 0xFFu
#define MOTA_QSPI_IO3_PIN 0xFFu
#define MOTA_QSPI_SCK_FREQ NRF_QSPI_FREQ_32MDIV4

#undef BLEDIS_MODEL
#define BLEDIS_MODEL "RAK4631"
#undef BLEDIS_MANUFACTURER
#define BLEDIS_MANUFACTURER "RAK"
#undef UF2_PRODUCT_NAME
#undef UF2_VOLUME_LABEL
#undef UF2_BOARD_ID
#define UF2_PRODUCT_NAME "RAK4631"
#define UF2_VOLUME_LABEL "4631A"
#define UF2_BOARD_ID "4631A"
#undef UF2_INDEX_URL
#define UF2_INDEX_URL "https://rakwireless.com"

#endif
