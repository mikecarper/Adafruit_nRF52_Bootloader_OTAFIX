set(CMAKE_SYSTEM_NAME Generic)

if (NOT DEFINED ARM_GNU_PREFIX)
  execute_process(
    COMMAND "${Python_EXECUTABLE}" "${MOTA_COMPILER_POLICY_TOOL}" --board "${BOARD}" --field prefix
    RESULT_VARIABLE MOTA_COMPILER_POLICY_RESULT
    OUTPUT_VARIABLE ARM_GNU_SELECTED_PREFIX OUTPUT_STRIP_TRAILING_WHITESPACE)
  if (NOT MOTA_COMPILER_POLICY_RESULT EQUAL 0)
    message(FATAL_ERROR
      "Board-qualified Arm GNU ${MOTA_ARM_GCC_PREFERRED} is unavailable; see compiler selection hint above")
  endif ()
else ()
  set(ARM_GNU_SELECTED_PREFIX "${ARM_GNU_PREFIX}")
endif ()
set(CMAKE_C_COMPILER "${ARM_GNU_SELECTED_PREFIX}gcc")
set(CMAKE_CXX_COMPILER "${ARM_GNU_SELECTED_PREFIX}g++")
set(CMAKE_ASM_COMPILER "${ARM_GNU_SELECTED_PREFIX}gcc")
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

set_property(GLOBAL PROPERTY TARGET_SUPPORTS_SHARED_LIBS FALSE)

# Look for includes and libraries only in the target system prefix.
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)

include(${CMAKE_CURRENT_LIST_DIR}/../cpu/${CMAKE_SYSTEM_PROCESSOR}.cmake)

# enable all possible warnings for building examples
list(APPEND TOOLCHAIN_COMMON_FLAGS
  -fdata-sections
  -ffunction-sections
  -fsingle-precision-constant
  -fno-strict-aliasing
  -g
  )

set(TOOLCHAIN_EXE_LINKER_FLAGS
  -Wl,--print-memory-usage
  -Wl,--gc-sections
  #-Wl,--cref
  )

# join the toolchain flags into a single string
list(JOIN TOOLCHAIN_COMMON_FLAGS " " TOOLCHAIN_COMMON_FLAGS)
list(JOIN TOOLCHAIN_EXE_LINKER_FLAGS " " CMAKE_EXE_LINKER_FLAGS_INIT)

set(CMAKE_C_FLAGS_INIT "${TOOLCHAIN_COMMON_FLAGS} ${TOOLCHAIN_C_FLAGS}")
set(CMAKE_ASM_FLAGS_INIT "${TOOLCHAIN_COMMON_FLAGS} ${TOOLCHAIN_ASM_FLAGS}")
