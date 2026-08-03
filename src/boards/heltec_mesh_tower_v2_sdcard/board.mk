include src/boards/heltec_mesh_tower_v2/board.mk
CFLAGS += -DMOTA_SD_CARD=1
C_SRC += src/ota_sd_spi.c
