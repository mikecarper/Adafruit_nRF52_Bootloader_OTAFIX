include src/boards/heltec_mesh_tower_v2/board.mk
CFLAGS := $(filter-out -DMOTA_INTERNAL_BOOTLOADER_UPDATE=1,$(CFLAGS))
CFLAGS += -DMOTA_SD_CARD=1
