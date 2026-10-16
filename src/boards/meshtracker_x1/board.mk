MCU_SUB_VARIANT = nrf52840
SD_VERSION = 7.3.0
CFLAGS += -DDEVICE_NAME='"X1INT_DFU"'
CFLAGS += -DMOTA_INTERNAL_BOOTLOADER_UPDATE=1

# Factory identity and basic controls are known; reset/power behavior still
# needs physical qualification. Never build an unlabelled production image.
ifneq ($(MOTA_BOOTLOADER_TEST_BUILD),1)
$(error MeshTracker X1 requires an explicit qualification build)
endif
ifeq ($(strip $(MOTA_BOOTLOADER_VERSION_TEST_OVERRIDE)),)
$(error MeshTracker X1 qualification checks require an explicit test version)
endif
CFLAGS += -DOTAFIX_X1_QUALIFICATION_ONLY=1
