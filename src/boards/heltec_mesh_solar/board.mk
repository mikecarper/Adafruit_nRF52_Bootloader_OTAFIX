MCU_SUB_VARIANT = nrf52840
SD_VERSION = 6.1.1
CFLAGS += -DDEVICE_NAME='"SOLARINT_DFU"'
CFLAGS += -DMOTA_INTERNAL_BOOTLOADER_UPDATE=1

# Carrier/DFU watchdog behavior must be physically qualified before promotion.
ifneq ($(MOTA_BOOTLOADER_TEST_BUILD),1)
$(error Mesh Solar requires an explicit qualification build)
endif
ifeq ($(strip $(MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE)),)
$(error Mesh Solar qualification checks require an explicit test version)
endif
CFLAGS += -DOTAFIX_SOLAR_QUALIFICATION_ONLY=1
