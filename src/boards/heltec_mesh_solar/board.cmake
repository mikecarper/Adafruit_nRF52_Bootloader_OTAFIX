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
  if(NOT OTAFIX_EXPERIMENTAL_PORT_PREVIEW)
    message(FATAL_ERROR "Mesh Solar qualification checks require an explicit test version")
  endif()
  execute_process(COMMAND git describe --exact-match --dirty --tags
    WORKING_DIRECTORY "${CMAKE_CURRENT_LIST_DIR}/../../.."
    RESULT_VARIABLE _solar_tag_result OUTPUT_VARIABLE _solar_tag
    ERROR_QUIET OUTPUT_STRIP_TRAILING_WHITESPACE)
  execute_process(COMMAND "${Python_EXECUTABLE}"
    "${CMAKE_CURRENT_LIST_DIR}/../../../tools/derive_otafix_version.py"
    "${_solar_tag}" --preview-only --hex
    RESULT_VARIABLE _solar_version_result OUTPUT_QUIET ERROR_QUIET)
  if(NOT _solar_tag_result EQUAL 0 OR NOT _solar_version_result EQUAL 0)
    message(FATAL_ERROR "Mesh Solar preview requires an exact clean OTAFIX preview tag")
  endif()
endif()
add_compile_definitions(OTAFIX_SOLAR_QUALIFICATION_ONLY=1)
