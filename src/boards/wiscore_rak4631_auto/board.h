#ifndef _WISCORE_RAK4631_AUTO_H
#define _WISCORE_RAK4631_AUTO_H

#include "../wiscore_rak4631_board/board.h"

// RAK15001 Slot C and the header-wired W25Q16 share SPI data/clock but
// use distinct chip selects. The loader probes exact JEDEC IDs at apply time.
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
#define BLEDIS_MODEL "RAK4631 Auto"
#undef UF2_PRODUCT_NAME
#undef UF2_VOLUME_LABEL
#undef UF2_BOARD_ID
#define UF2_PRODUCT_NAME "RAK4631 Auto"
#define UF2_VOLUME_LABEL "4631AUTO"
#define UF2_BOARD_ID "WisBlock-RAK4631-Auto"

#endif
