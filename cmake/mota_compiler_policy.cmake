# The all-in-one RAK4631 profile needs GCC 15.3 to fit the unchanged executable
# envelope. Other profiles retain the existing Arm GNU 14.2 minimum.
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
  if (NOT compiler_id STREQUAL "GNU" OR
      compiler_version VERSION_LESS MOTA_ARM_GCC_MINIMUM)
    message(FATAL_ERROR
      "Arm GNU Toolchain ${MOTA_ARM_GCC_MINIMUM}.Rel1 or newer is required for ${BOARD}; "
      "found ${compiler_id} ${compiler_version}. Select the matching arm-none-eabi-gcc "
      "on PATH (Docker: --build-arg ARM_GNU_RELEASE=${MOTA_ARM_GCC_MINIMUM}.rel1).")
  endif ()
endfunction()
