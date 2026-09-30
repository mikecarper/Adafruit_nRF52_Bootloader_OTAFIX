MCU_SUB_VARIANT = nrf52840
CFLAGS += -DDEVICE_NAME='"TNM8_DFU"'
CFLAGS += -DMOTA_QSPI_FLASH=1
CFLAGS += -DMOTA_QSPI_BOOTLOADER_UPDATE=1

# No factory USB identity yet: allow compiler checks, never production builds.
ifneq ($(MOTA_BOOTLOADER_TEST_BUILD),1)
$(error ThinkNode M8 is compile-only until its factory USB identity is verified)
endif
ifeq ($(strip $(MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE)),)
$(error ThinkNode M8 compile-only checks require an explicit test version)
endif
CFLAGS += -DOTAFIX_M8_COMPILE_ONLY=1
