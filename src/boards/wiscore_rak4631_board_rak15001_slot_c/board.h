#ifndef _WISCORE_RAK4631_BOARD_RAK15001_SLOT_C_H
#define _WISCORE_RAK4631_BOARD_RAK15001_SLOT_C_H

#include "../wiscore_rak4631_board/board.h"

// RAK15001 in WisBlock sensor Slot C. The module is standard (1-1-1) SPI,
// despite using the nRF52840 QSPI peripheral for EasyDMA-backed access.
#define MOTA_QSPI_SCK_PIN _PINNUM(0, 3)
#define MOTA_QSPI_CSN_PIN _PINNUM(0, 26)
#define MOTA_QSPI_IO0_PIN _PINNUM(0, 30) // MOSI
#define MOTA_QSPI_IO1_PIN _PINNUM(0, 29) // MISO
#define MOTA_QSPI_IO2_PIN 0xFFu           // not connected; RAK15001 has no quad-I/O mode
#define MOTA_QSPI_IO3_PIN 0xFFu           // not connected; RAK15001 has no quad-I/O mode
#define MOTA_QSPI_SCK_FREQ NRF_QSPI_FREQ_32MDIV4 // 8 MHz (module maximum is 15 MHz)

// Require the exact 2 MiB GigaDevice GD25Q16 fitted to RAK15001. This keeps a
// different device sharing the WisBlock SPI bus from being mistaken for the
// OTA staging store.
#define MOTA_QSPI_JEDEC_MANUFACTURER 0xC8u
#define MOTA_QSPI_JEDEC_MEMORY_TYPE  0x40u
#define MOTA_QSPI_JEDEC_CAPACITY     0x15u

// WP# and HOLD# both have 10 kOhm pull-ups on the RAK15001. Do not drive
// WB_IO4 here; it may also be connected to another module on the baseboard.

#undef BLEDIS_MODEL
#define BLEDIS_MODEL "RAK4631 + RAK15001 Slot C"

#undef UF2_PRODUCT_NAME
#undef UF2_VOLUME_LABEL
#undef UF2_BOARD_ID
#undef UF2_INDEX_URL
#define UF2_PRODUCT_NAME "WisBlock RAK4631 + RAK15001 C"
#define UF2_VOLUME_LABEL "RAK15001C"
#define UF2_BOARD_ID     "WisBlock-RAK4631-RAK15001-Slot-C"
#define UF2_INDEX_URL    "https://docs.rakwireless.com/product-categories/wisblock/rak15001/overview/"

#endif // _WISCORE_RAK4631_BOARD_RAK15001_SLOT_C_H
