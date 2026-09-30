set(MCU_VARIANT nrf52840)
set(DEVICE_NAME TNM8_DFU)
set(OTAFIX_BOARD_QUALIFICATION_PENDING ON)
set(MOTA_QSPI_FLASH ON)
set(MOTA_QSPI_BOOTLOADER_UPDATE ON)

# No factory USB identity yet: allow compiler checks, never production builds.
if(NOT MOTA_BOOTLOADER_TEST_BUILD)
  message(FATAL_ERROR "ThinkNode M8 is compile-only until its factory USB identity is verified")
endif()
if(NOT DEFINED MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE OR
   MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE STREQUAL "")
  message(FATAL_ERROR "ThinkNode M8 compile-only checks require an explicit test version")
endif()
add_compile_definitions(OTAFIX_M8_COMPILE_ONLY=1)
