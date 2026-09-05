# Host test for the MeshCore .mota in-place apply - runs the REAL bootloader apply (ota_delta.c) over a
# simulated flash, NO hardware. See README.md.
#
#   make check                                  # apply the committed vector, assert success
#   ./apply_sim <base.img> <delta.mota> <new.img>   # debug any scenario (e.g. real firmware images)

CC      ?= gcc
CFLAGS  ?= -std=c11 -O2 -Wall -Wextra -Wno-unused-parameter
SANITIZER_CFLAGS = -std=c11 -O1 -g -Wall -Wextra -Wno-unused-parameter \
	-fsanitize=address,undefined -fno-omit-frame-pointer
SRC      = ../src
INC      = -I $(SRC) -I $(SRC)/detools
PSTORAGE_SRC = ../lib/sdk11/components/drivers_nrf/pstorage/pstorage_raw.c
PSTORAGE_INC = -I pstorage_stubs -I ../lib/sdk11/components/drivers_nrf/pstorage
PEER_DATA_INC = -I $(SRC) \
	-I ../lib/sdk11/components/libraries/bootloader_dfu \
	-I ../lib/sdk11/components/libraries/util \
	-I ../lib/nrfx/mdk -I $(SRC)/cmsis/include
S132_V6_INC = -I ../lib/softdevice/s132_nrf52_6.1.1/s132_nrf52_6.1.1_API/include \
	-I ../lib/softdevice/s132_nrf52_6.1.1/s132_nrf52_6.1.1_API/include/nrf52
S140_V6_INC = -I ../lib/softdevice/s140_nrf52_6.1.1/s140_nrf52_6.1.1_API/include \
	-I ../lib/softdevice/s140_nrf52_6.1.1/s140_nrf52_6.1.1_API/include/nrf52
S140_V7_INC = -I ../lib/softdevice/s140_nrf52_7.3.0/s140_nrf52_7.3.0_API/include \
	-I ../lib/softdevice/s140_nrf52_7.3.0/s140_nrf52_7.3.0_API/include/nrf52
DFU_INIT_INC = -I $(SRC) -I ../lib/sdk11/components/libraries/bootloader_dfu \
	-I ../lib/sdk/components/libraries/util \
	-I ../lib/sdk/components/libraries/crc16 \
	-I ../lib/nrfx/mdk -I $(SRC)/cmsis/include $(S140_V6_INC) \
	-I ../lib/tinycrypt/lib/include
DFU_INIT_FLAGS = -DNRF52840_XXAA -DS140 -DSVCALL_AS_NORMAL_FUNCTION \
	-DDFU_APP_DATA_RESERVED=0xA000
DFU_INIT_HOST_WARNINGS = -Wno-implicit-function-declaration -Wno-pointer-to-int-cast \
	-Wno-unused-variable

apply_sim: apply_sim.c $(SRC)/ota_delta.c $(SRC)/detools/detools.c $(SRC)/sha256.c \
           $(SRC)/ota_delta.h $(SRC)/ota_layout.h
	$(CC) $(CFLAGS) -DOTA_DELTA_HOST_TEST $(INC) apply_sim.c $(SRC)/detools/detools.c $(SRC)/sha256.c -o $@

# Regression test for the -flto flash-readback aliasing bug (positive + negative behaviour + source guard).
readback_test: readback_test.c $(SRC)/ota_delta.c $(SRC)/detools/detools.c $(SRC)/sha256.c \
               $(SRC)/ota_delta.h $(SRC)/ota_layout.h
	$(CC) $(CFLAGS) -DOTA_DELTA_HOST_TEST $(INC) readback_test.c $(SRC)/detools/detools.c $(SRC)/sha256.c -o $@

readback_test_v7: readback_test.c $(SRC)/ota_delta.c $(SRC)/detools/detools.c $(SRC)/sha256.c \
                  $(SRC)/ota_delta.h $(SRC)/ota_layout.h
	$(CC) $(CFLAGS) -DOTA_DELTA_HOST_TEST -DMOTA_NRF52_APP_BASE=0x00027000u $(INC) \
		readback_test.c $(SRC)/detools/detools.c $(SRC)/sha256.c -o $@

readback_internal_test: readback_test.c $(SRC)/ota_delta.c $(SRC)/detools/detools.c $(SRC)/sha256.c \
                        $(SRC)/usb/uf2/bootloader_image.c $(SRC)/usb/uf2/bootloader_image.h \
                        $(SRC)/ota_delta.h $(SRC)/ota_layout.h
	$(CC) $(CFLAGS) -DOTA_DELTA_HOST_TEST -DMOTA_INTERNAL_BOOTLOADER_UPDATE \
		-DUSB_DESC_VID=0x239A -DUSB_DESC_UF2_PID=0x0029 -DDEVICE_NAME='"3401_DFU"' $(INC) \
		readback_test.c $(SRC)/detools/detools.c $(SRC)/sha256.c \
		$(SRC)/usb/uf2/bootloader_image.c -o $@

bootloader_image_test: bootloader_image_test.c $(SRC)/usb/uf2/bootloader_image.c \
                       $(SRC)/usb/uf2/bootloader_image.h
	$(CC) $(CFLAGS) -I $(SRC) bootloader_image_test.c $(SRC)/usb/uf2/bootloader_image.c -o $@

sd_apply_test: sd_apply_test.c $(SRC)/ota_delta.c $(SRC)/detools/detools.c $(SRC)/sha256.c \
               $(SRC)/ota_delta.h $(SRC)/ota_layout.h $(SRC)/ota_sd_auth.h $(SRC)/ota_sd_spi.h
	$(CC) $(CFLAGS) -DOTA_DELTA_HOST_TEST -DMOTA_SD_CARD $(INC) sd_apply_test.c \
		$(SRC)/detools/detools.c $(SRC)/sha256.c -o $@

qspi_apply_test: sd_apply_test.c $(SRC)/ota_delta.c $(SRC)/detools/detools.c $(SRC)/sha256.c \
                 $(SRC)/ota_delta.h $(SRC)/ota_layout.h $(SRC)/ota_qspi.h
	$(CC) $(CFLAGS) -DOTA_DELTA_HOST_TEST -DMOTA_QSPI_FLASH $(INC) sd_apply_test.c \
		$(SRC)/detools/detools.c $(SRC)/sha256.c -o $@

bootloader_mota_test: bootloader_mota_test.c $(SRC)/ota_delta.c $(SRC)/detools/detools.c \
                      $(SRC)/sha256.c $(SRC)/usb/uf2/bootloader_image.c \
                      $(SRC)/usb/uf2/bootloader_image.h $(SRC)/ota_bl_info.h $(SRC)/ota_layout.h
	$(CC) $(CFLAGS) -DOTA_DELTA_HOST_TEST -DMOTA_QSPI_FLASH -DMOTA_QSPI_BOOTLOADER_UPDATE \
		-DUSB_DESC_VID=0x2886 -DUSB_DESC_UF2_PID=0x0044 -DDEVICE_NAME='"XIAO_DFU"' $(INC) \
		bootloader_mota_test.c $(SRC)/detools/detools.c $(SRC)/sha256.c \
		$(SRC)/usb/uf2/bootloader_image.c -o $@

bootloader_mota_internal_test: bootloader_mota_test.c $(SRC)/ota_delta.c $(SRC)/detools/detools.c \
                               $(SRC)/sha256.c $(SRC)/usb/uf2/bootloader_image.c \
                               $(SRC)/usb/uf2/bootloader_image.h $(SRC)/ota_bl_info.h $(SRC)/ota_layout.h
	$(CC) $(CFLAGS) -DOTA_DELTA_HOST_TEST -DMOTA_INTERNAL_BOOTLOADER_UPDATE \
		-DUSB_DESC_VID=0x239A -DUSB_DESC_UF2_PID=0x0029 -DDEVICE_NAME='"3401_DFU"' $(INC) \
		bootloader_mota_test.c $(SRC)/detools/detools.c $(SRC)/sha256.c \
		$(SRC)/usb/uf2/bootloader_image.c -o $@

bootloader_mota_sd_test: bootloader_mota_test.c $(SRC)/ota_delta.c $(SRC)/detools/detools.c \
                         $(SRC)/sha256.c $(SRC)/usb/uf2/bootloader_image.c \
                         $(SRC)/usb/uf2/bootloader_image.h $(SRC)/ota_bl_info.h $(SRC)/ota_layout.h \
                         $(SRC)/ota_sd_auth.h $(SRC)/ota_sd_boot_token.h $(SRC)/ota_sd_spi.h
	$(CC) $(CFLAGS) -DOTA_DELTA_HOST_TEST -DMOTA_SD_CARD -DMOTA_SD_BOOTLOADER_UPDATE \
		-DUSB_DESC_VID=0x239A -DUSB_DESC_UF2_PID=0x0071 -DDEVICE_NAME='"TOWER_V2_OTA"' $(INC) \
		bootloader_mota_test.c $(SRC)/detools/detools.c $(SRC)/sha256.c \
		$(SRC)/usb/uf2/bootloader_image.c -o $@

softdevice_fwid_test: softdevice_fwid_test.c $(SRC)/ota_softdevice_fwid.h
	$(CC) $(CFLAGS) -I $(SRC) softdevice_fwid_test.c -o $@

dfu_init_bounds_test: dfu_init_bounds_test.c $(SRC)/dfu_init.c
	$(CC) $(CFLAGS) $(DFU_INIT_HOST_WARNINGS) $(DFU_INIT_FLAGS) $(DFU_INIT_INC) \
		dfu_init_bounds_test.c $(SRC)/dfu_init.c -o $@

dfu_init_signed_bounds_test: dfu_init_bounds_test.c dfu_init_signed_under_test.c \
                             $(SRC)/dfu_init.c
	$(CC) $(CFLAGS) $(DFU_INIT_HOST_WARNINGS) -DSIGNED_FW $(DFU_INIT_FLAGS) $(DFU_INIT_INC) \
		dfu_init_bounds_test.c dfu_init_signed_under_test.c -o $@

qspi_alignment_test: qspi_alignment_test.c $(SRC)/ota_qspi_alignment.h
	$(CC) $(CFLAGS) -I $(SRC) qspi_alignment_test.c -o $@

qspi_wake_test: qspi_wake_test.c $(SRC)/ota_qspi_wake.h $(SRC)/ota_qspi.c
	$(CC) $(CFLAGS) -I $(SRC) qspi_wake_test.c -o $@

usb_wait_test: usb_wait_test.c $(SRC)/usb/usb_wait.c $(SRC)/usb/usb_wait.h
	$(CC) $(CFLAGS) -DUSB_WAIT_HOST_TEST -I $(SRC)/usb usb_wait_test.c $(SRC)/usb/usb_wait.c -o $@

dfu_timeout_test: dfu_timeout_test.c $(SRC)/dfu_timeout.h
	$(CC) $(CFLAGS) -I $(SRC) dfu_timeout_test.c -o $@

uf2_write_state_test: uf2_write_state_test.c $(SRC)/usb/uf2/uf2_app_flash.h \
                      $(SRC)/usb/uf2/uf2_transfer_state.h \
                      $(SRC)/usb/uf2/uf2_current_echo.h
	$(CC) $(CFLAGS) -I $(SRC)/usb/uf2 uf2_write_state_test.c -o $@

bootloader_settings_guard_test: bootloader_settings_guard_test.c \
                                $(SRC)/bootloader_settings_guard.c \
                                $(SRC)/bootloader_settings_guard.h
	$(CC) $(CFLAGS) -I $(SRC) \
		-I ../lib/sdk11/components/libraries/bootloader_dfu \
		-I ../lib/sdk/components/libraries/crc16 \
		bootloader_settings_guard_test.c $(SRC)/bootloader_settings_guard.c -o $@

dfu_image_policy_test: dfu_image_policy_test.c $(SRC)/dfu_image_policy.c \
                       $(SRC)/dfu_image_policy.h $(SRC)/usb/uf2/bootloader_image.c
	$(CC) $(CFLAGS) $(DFU_INIT_HOST_WARNINGS) $(DFU_INIT_FLAGS) \
		-DDFU_IMAGE_POLICY_HOST_TEST -DMOTA_SOFTDEVICE_FAMILY=140 \
		-DDEVICE_NAME='"T096_DFU"' $(DFU_INIT_INC) \
		-I $(SRC)/boards -I $(SRC)/boards/heltec_t096 \
		dfu_image_policy_test.c $(SRC)/dfu_image_policy.c \
		$(SRC)/usb/uf2/bootloader_image.c -o $@

dfu_entry_test: dfu_entry_test.c $(SRC)/dfu_entry.h
	$(CC) $(CFLAGS) -I $(SRC) dfu_entry_test.c -o $@

peer_data_layout_test: peer_data_layout_test.c $(SRC)/dfu_ble_peer_data_layout.h \
                       ../lib/sdk11/components/libraries/bootloader_dfu/dfu_ble_svc.h
	$(CC) $(CFLAGS) -DSVCALL_AS_NORMAL_FUNCTION -DNRF52840_XXAA -DS140 $(PEER_DATA_INC) $(S140_V6_INC) peer_data_layout_test.c -o $@

peer_data_layout_nrf52_test: peer_data_layout_test.c $(SRC)/dfu_ble_peer_data_layout.h \
                             ../lib/sdk11/components/libraries/bootloader_dfu/dfu_ble_svc.h
	$(CC) $(CFLAGS) -DSVCALL_AS_NORMAL_FUNCTION -DNRF52 -DNRF52832_XXAA -DS132 $(PEER_DATA_INC) $(S132_V6_INC) peer_data_layout_test.c -o $@

peer_data_layout_nrf52833_test: peer_data_layout_test.c $(SRC)/dfu_ble_peer_data_layout.h \
                                ../lib/sdk11/components/libraries/bootloader_dfu/dfu_ble_svc.h
	$(CC) $(CFLAGS) -DSVCALL_AS_NORMAL_FUNCTION -DNRF52833_XXAA -DS140 $(PEER_DATA_INC) $(S140_V7_INC) peer_data_layout_test.c -o $@

pstorage_busy_test: pstorage_busy_test.c $(PSTORAGE_SRC) $(wildcard pstorage_stubs/*.h)
	$(CC) $(CFLAGS) -Wno-int-to-pointer-cast -DNRF52_SERIES $(PSTORAGE_INC) \
		pstorage_busy_test.c $(PSTORAGE_SRC) -o $@

check: apply_sim readback_test readback_test_v7 readback_internal_test bootloader_image_test sd_apply_test qspi_apply_test bootloader_mota_test bootloader_mota_internal_test bootloader_mota_sd_test softdevice_fwid_test dfu_init_bounds_test dfu_init_signed_bounds_test qspi_alignment_test qspi_wake_test usb_wait_test dfu_timeout_test uf2_write_state_test bootloader_settings_guard_test dfu_image_policy_test dfu_entry_test peer_data_layout_test peer_data_layout_nrf52_test peer_data_layout_nrf52833_test pstorage_busy_test
	python3 version_derivation_test.py
	python3 build_profile_test.py
	python3 build_all_test.py
	python3 manifest_patcher_test.py
	python3 cf2_guard_test.py
	python3 peer_data_linker_test.py
	python3 bootloader_handoff_test.py
	python3 ble_advertising_test.py
	python3 ble_dis_layout_test.py
	python3 ble_connection_policy_test.py
	python3 serial_dfu_erase_test.py
	python3 sd_spi_guard_test.py
	python3 lfclk_source_test.py
	python3 svc_ipa_guard_test.py
	python3 legacy_dfu_bounds_test.py
	python3 legacy_ble_dfu_host_test.py
	python3 signed_legacy_package_test.py
	python3 usb_descriptor_test.py
	python3 usb_task_budget_test.py
	python3 uf2_243_differential_test.py
	python3 uf2_handoff_test.py
	python3 uf2_drive_hil_test.py
	python3 test_otafix_mota_update.py
	python3 bootloader_mota_release_test.py
	python3 ../tools/check_internal_bootloader_targets.py
	@echo
	./apply_sim vectors/base.img vectors/delta.mota vectors/new.img
	@echo
	./readback_test
	@echo
	./readback_test_v7
	@echo
	./readback_internal_test
	@echo
	./bootloader_image_test
	@echo
	./sd_apply_test
	@echo
	./qspi_apply_test
	@echo
	./bootloader_mota_test
	@echo
	./bootloader_mota_internal_test
	@echo
	./bootloader_mota_sd_test
	@echo
	./softdevice_fwid_test
	@echo
	./dfu_init_bounds_test
	./dfu_init_signed_bounds_test
	@echo
	./qspi_alignment_test
	@echo
	./qspi_wake_test
	@echo
	./usb_wait_test
	@echo
	./dfu_timeout_test
	@echo
	./uf2_write_state_test
	@echo
	./bootloader_settings_guard_test
	@echo
	./dfu_image_policy_test
	@echo
	./dfu_entry_test
	@echo
	./peer_data_layout_test
	./peer_data_layout_nrf52_test
	./peer_data_layout_nrf52833_test
	@echo
	./pstorage_busy_test

sanitize:
	$(MAKE) clean
	$(MAKE) CFLAGS="$(SANITIZER_CFLAGS)" check

clean:
	rm -f apply_sim readback_test readback_test_v7 readback_internal_test bootloader_image_test sd_apply_test qspi_apply_test bootloader_mota_test bootloader_mota_internal_test bootloader_mota_sd_test softdevice_fwid_test dfu_init_bounds_test dfu_init_signed_bounds_test qspi_alignment_test qspi_wake_test usb_wait_test dfu_timeout_test uf2_write_state_test bootloader_settings_guard_test dfu_image_policy_test dfu_entry_test peer_data_layout_test peer_data_layout_nrf52_test peer_data_layout_nrf52833_test pstorage_busy_test

.PHONY: check sanitize clean
