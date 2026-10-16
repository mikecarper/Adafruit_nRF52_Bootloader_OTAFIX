set(MCU_VARIANT nrf52840)
set(DEVICE_NAME SOLARINT_DFU)
set(SD_VERSION 6.1.1)
set(OTAFIX_BOARD_QUALIFICATION_PENDING ON)
set(MOTA_INTERNAL_BOOTLOADER_UPDATE ON)

# Carrier/DFU watchdog behavior must be physically qualified before promotion.
if(NOT MOTA_BOOTLOADER_TEST_BUILD)
  message(FATAL_ERROR "Mesh Solar requires an explicit qualification build")
endif()
if(NOT DEFINED MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE OR
   MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE STREQUAL "")
  message(FATAL_ERROR "Mesh Solar qualification checks require an explicit test version")
endif()
add_compile_definitions(OTAFIX_SOLAR_QUALIFICATION_ONLY=1)
