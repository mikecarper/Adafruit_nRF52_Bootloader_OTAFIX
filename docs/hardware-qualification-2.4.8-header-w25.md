# Adaptive RAK header W25Q16 local qualification

Date: 2026-09-25. Candidate commit: `44904b3`. These are local hardware results;
the `OTAFIX2.4.8` GitHub release and tag were not updated by this trial.

## RAK4631 with header W25Q16

- Physical USB serial `9AB3B64C641BA927`; the RAK19007 2.54 mm headers carry
  CLK on J10 TX1, DO on J10 RX1, DI on J11 IO1, CS on J11 AIN1, and 3.3 V/GND
  on J12. CS has a physical 10 kΩ pull-up to 3.3 V.
- The unified MeshCore `2724bab5` application read JEDEC `EF4015`. A temporary
  diagnostic build erased all 512 4 KiB sectors, read every byte as `FF`,
  programmed every byte as `00`, and read every byte as `00`. The normal
  1.17.1.7 application was restored afterward.
- From the prior merged OTAFIX 2.4.8 loader, its USB boot drive accepted the
  88,064-byte `update-wiscore_rak4631_auto_bootloader-OTAFIX2.4.8_mbr.uf2`
  (`SHA-256 ad9370ded48a14bbfa403ac7d2a3d2c99c0f03e246bc1b936801b2d3d2eeaf17`).
  The running application then reported `QSPI W25Q16 header jedec=EF4015
  size=2048K` and `bootloader: QSPI apply OK`, with its original application
  version and serial console intact.

## RAK3401 USB migration control

- Physical USB serial `0B81C9C68D8D01B4`; SWD remained connected for recovery
  and readback. The prior merged OTAFIX 2.4.8 bootloader region had SHA-256
  `c7880621c9dc62968d1f7b6a7fb824fc93e0b80c743a59714c2f0c99bff7707b`.
- Its USB boot drive accepted the 88,064-byte
  `update-wiscore_rak3401_auto_bootloader-OTAFIX2.4.8_mbr.uf2`
  (`SHA-256 851c4f8a85e52831e2ee1b127706ae27c4920aeb61e7873cf5d8cd7f0b28cfda`).
  Guarded SWD readback of the 40 KiB bootloader region matched the candidate
  SHA-256 `b9c03fc714f2c08775522580b749b3d5bb8c1dcd48215ec874c3051a6ecbe767`.
- The Full Companion application bytes verified after migration, but its USB
  serial console did not respond following warm resets. Unplugging and
  reconnecting only RAK3401 USB restored its version reply. The RAK3401
  had no external W25Q16 fitted for this trial.

The RAK4631 flash pattern test and QSPI capability check do not constitute a
completed LoRa mOTA install. A full or delta external-flash bootloader apply
remains to be tested separately.
