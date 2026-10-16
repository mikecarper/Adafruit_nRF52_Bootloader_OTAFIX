set(MCU_VARIANT nrf52840)
set(DEVICE_NAME X1INT_DFU)
set(SD_VERSION 7.3.0)
set(OTAFIX_BOARD_QUALIFICATION_PENDING ON)
set(MOTA_INTERNAL_BOOTLOADER_UPDATE ON)

# Factory identity and basic controls are known; reset/power behavior still
# needs physical qualification. Never build an unlabelled production image.
if(NOT MOTA_BOOTLOADER_TEST_BUILD)
  message(FATAL_ERROR "MeshTracker X1 requires an explicit qualification build")
endif()
if(NOT DEFINED MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE OR
   MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE STREQUAL "")
  message(FATAL_ERROR "MeshTracker X1 qualification checks require an explicit test version")
endif()
add_compile_definitions(OTAFIX_X1_QUALIFICATION_ONLY=1)
