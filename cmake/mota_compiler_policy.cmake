# Keep release selection in one table shared with Make, build_all and CI.
if (NOT Python_EXECUTABLE)
  find_package(Python REQUIRED COMPONENTS Interpreter)
endif ()
set(MOTA_COMPILER_POLICY_TOOL "${CMAKE_CURRENT_LIST_DIR}/../tools/compiler_policy.py")
if (NOT CMAKE_SCRIPT_MODE_FILE)
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    "${MOTA_COMPILER_POLICY_TOOL}" "${CMAKE_CURRENT_LIST_DIR}/../tools/compiler_policy.json")
endif ()
execute_process(COMMAND "${Python_EXECUTABLE}" "${MOTA_COMPILER_POLICY_TOOL}" --board "${BOARD}"
  RESULT_VARIABLE MOTA_COMPILER_POLICY_RESULT
  OUTPUT_VARIABLE MOTA_ARM_GCC_PREFERRED OUTPUT_STRIP_TRAILING_WHITESPACE)
if (NOT MOTA_COMPILER_POLICY_RESULT EQUAL 0)
  message(FATAL_ERROR "Cannot select the board-qualified Arm GNU release")
endif ()

# The combined RAK4631 minimum also applies to explicit qualification overrides.
set(MOTA_ARM_GCC_MINIMUM "14.2")
set(MOTA_RAK_SD_SIZE_OPTIONS)
if (MOTA_RAK_SD_STORE AND BOARD STREQUAL "wiscore_rak4631_auto")
  set(MOTA_ARM_GCC_MINIMUM "15.3")
  # Apply to compilation AND the LTO link. These pass choices preserve C
  # object identity, all update/recovery features and every validation check.
  set(MOTA_RAK_SD_SIZE_OPTIONS
    -fno-schedule-insns
    -fno-schedule-insns2
    -fno-code-hoisting
    -fno-tree-ter
    -fno-tree-dominator-opts
    -fno-tree-tail-merge
    -fno-optimize-sibling-calls
    -fno-if-conversion
    -mbranch-cost=3
    -fno-tree-loop-im
    -fno-early-inlining)
endif ()

function(mota_require_arm_gcc compiler_id compiler_version)
  if (DEFINED ARM_GNU_SELECTED_PREFIX)
    # Resolve relative qualification prefixes and Windows executable suffixes
    # with the same host program search that CMake uses for the compiler.
    unset(MOTA_SELECTED_COMPILER_PROGRAM CACHE)
    find_program(MOTA_SELECTED_COMPILER_PROGRAM
      NAMES "${ARM_GNU_SELECTED_PREFIX}gcc" "${ARM_GNU_SELECTED_PREFIX}gcc.exe"
      NO_CMAKE_FIND_ROOT_PATH)
    if (NOT MOTA_SELECTED_COMPILER_PROGRAM)
      message(FATAL_ERROR "Cannot find selected compiler ${ARM_GNU_SELECTED_PREFIX}gcc")
    endif ()
    get_filename_component(selected_compiler "${MOTA_SELECTED_COMPILER_PROGRAM}" REALPATH)
    unset(MOTA_SELECTED_COMPILER_PROGRAM CACHE)
    get_filename_component(configured_compiler "${CMAKE_C_COMPILER}" REALPATH)
    if (CMAKE_HOST_WIN32)
      string(TOLOWER "${selected_compiler}" selected_compiler)
      string(TOLOWER "${configured_compiler}" configured_compiler)
    endif ()
    if (NOT selected_compiler STREQUAL configured_compiler)
      message(FATAL_ERROR
        "This CMake build directory uses ${CMAKE_C_COMPILER}, but compiler selection now requires "
        "${ARM_GNU_SELECTED_PREFIX}gcc. Configure a fresh build directory to change compilers.")
    endif ()
  endif ()
  if (NOT compiler_id STREQUAL "GNU" OR
      compiler_version VERSION_LESS MOTA_ARM_GCC_MINIMUM)
    message(FATAL_ERROR
      "Arm GNU Toolchain ${MOTA_ARM_GCC_MINIMUM}.Rel1 or newer is required for ${BOARD}; "
      "found ${compiler_id} ${compiler_version}. Select the matching arm-none-eabi-gcc "
      "on PATH (Docker: --build-arg ARM_GNU_RELEASE=${MOTA_ARM_GCC_MINIMUM}.rel1).")
  endif ()
endfunction()
