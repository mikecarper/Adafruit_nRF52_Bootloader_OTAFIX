# Keep the reviewed three-backend exception board-bound. This file deliberately
# contains no compiler/target setup so host tests can exercise the actual guard.
if (MOTA_RAK_SD_STORE)
  if (NOT BOARD STREQUAL "wiscore_rak4631_auto" OR
      NOT MCU_VARIANT STREQUAL "nrf52840" OR
      NOT MOTA_RAK_AUTO_STORE OR NOT MOTA_QSPI_FLASH OR NOT MOTA_SD_CARD OR
      NOT MOTA_INTERNAL_BOOTLOADER_UPDATE OR
      MOTA_SD_BOOTLOADER_UPDATE OR MOTA_QSPI_BOOTLOADER_UPDATE OR
      NOT MOTA_RAM_ARENA_SIZE MATCHES "^(65536|0[xX]10000)$" OR
      MOTA_SD_DUAL_STORE)
    message(FATAL_ERROR
      "RAK SD storage requires the exact combined RAK4631 adaptive profile")
  endif ()
endif ()

if (MOTA_SD_CARD AND MOTA_QSPI_FLASH AND NOT MOTA_RAK_SD_STORE)
  message(FATAL_ERROR
    "Combined SD/QSPI storage is qualified only for the RAK4631 adaptive profile")
endif ()
