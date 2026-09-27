# Adaptive RAK bootloader recovery hardware result (2026-09-27)

A RAK3401 on MercerWoodMesh was tested with its exact OTAFIX 2.4.8 adaptive
bootloader (`3401_AUTO_DFU`, target `D04AB3AB`, ABI 2, flags `0x16`) and a
temporary MeshCore repeater application. The original 1 MiB flash and UICR
were backed up before the test.

The device received the official signed 2.4.9 preview bootloader package
over LoRa. MeshCore verified its signer, exact board identity, version, and
SHA-256, then copied the 40 KiB candidate to `0xE2000..0xEC000`. SWD readback
confirmed the staged bytes matched the signed payload. The application then
called `SD_MBR_COMMAND_COPY_BL` with the documented source and length.

The SWD trace reached the MBR SVC vector at `0x00000AA4`, then hit
`HardFault_Handler` with `CFSR=0x00000400` (imprecise bus fault). The MBR
parameter page at `0xFE000` remained erased and the installed bootloader
remained 2.4.8. ACL region 1 was `ADDR=0x000F4000`, `SIZE=0x0000C000`,
`PERM=0x00000002`, protecting both the bootloader and MBR parameter page
before the application ran. Calling the MBR with SoftDevice enabled or
disabled produced the same result. The application cannot clear this ACL
region without resetting through the existing bootloader.

Therefore a MeshCore application cannot bootstrap bootloader self-update on
the deployed adaptive RAK 2.4.8 profiles. The release builder excludes
`wiscore_rak3401_auto` and `wiscore_rak4631_auto` from signed bootloader mOTA
bundles. Use their exact-board UF2 or local DFU files for migration.

After the test, the original flash and UICR were restored and verified by
full readback. The before and after SHA-256 values were respectively
`621e298388d772f1606eb39e48368263762d2258080d7da97f104236de0aad90`
for flash and
`d029ea630c2f632a1b690cb52b2a96a28b6f870c656c3e1bd74ba3a571c53b9c`
for UICR. The original Companion application and radio settings were also
confirmed over USB serial.
