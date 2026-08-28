# Supported Boards

## Adafruit Boards

| Board | Name | VID PID | URL |
| --- | --- | --- | --- |

## 3rd Party Boards

| Board | Name | VID PID | URL |
| --- | --- | --- | --- |
| gat562 | MTools Tec GAT562 | 0x239A:0x0029 | https://github.com/gat-iot/GAT562-family |
| heltec_mesh_pocket | Heltec Mesh Pocket | 0x239A:0x0071 | https://heltec.org/project/mesh-pocket/ |
| heltec_mesh_tower_v2 | Heltec MeshTower V2 | 0x239A:0x0071 | https://heltec.org/project/meshtower/ |
| heltec_t096 | HT-n5262G | 0x239A:0x0071 | https://heltec.org/project/t096/ |
| heltec_t1 | Heltec Mesh Node T1 | 0x239A:0x0071 | https://heltec.org/project/mesh-node-t1/ |
| heltec_t114 | HT-n5262 | 0x239A:0x0071 | https://heltec.org/project/mesh-node-t114/ |
| keepteen_lt1 | Keepteen LT1 | 0x239A:0x00B3 | https://www.keepteen.com/ |
| lilygo_techo | LilyGo T-Echo | 0x239A:0x0029 | https://lilygo.cc/products/t-echo-lilygo |
| minewsemi_mx25le01 | MinewSemi MX25LE01 | 0x239A:0x0029 | https://www.minewsemi.com |
| promicro_nrf52840 | ProMicro NRF52840 | 0x239A:0x00B3 | https://www.nologo.tech/product/otherboard/NRF52840.html |
| sensecap_solar_p1 | Seeed Solar Node P1 | 0x2886:0x0044 | https://www.seeedstudio.com/ |
| t1000_e | Seeed T1000-E for Meshtastic | 0x2886:0x0057 | https://www.seeedstudio.com/SenseCAP-Card-Tracker-T1000-E-for-Meshtastic-p-5913.html |
| thinknode_m1 | ELECROW ThinkNodeM1 | 0x239A:0x00DA | https://www.elecrow.com |
| thinknode_m3 | ELECROW ThinkNode-M3 | 0x239A:0x00DA | https://www.elecrow.com |
| thinknode_m6 | ELECROW ThinkNodeM6 | 0x239A:0x00DA | https://www.elecrow.com |
| wio_tracker_l1 | Seeed TRACKER L1 | 0x2886:0x1667 | https://www.seeedstudio.com/ |
| wiscore_rak3401 | WisBlock RAK3401 | 0x239A:0x0029 | https://docs.rakwireless.com/product-categories/wisblock/rak3401/overview/ |
| wiscore_rak4631_board | WisBlock RAK4631 Board | 0x239A:0x0029 | https://store.rakwireless.com/collections/wisblock-core |
| wiscore_rak4631_board_rak15001_slot_c | WisBlock RAK4631 + RAK15001 (Sensor Slot C) | 0x239A:0x0029 | https://docs.rakwireless.com/product-categories/wisblock/rak15001/overview/ |
| wismesh_tag | WisMesh Tag | 0x239A:0x0029 | https://store.rakwireless.com/products/wismesh-tag-meshtastic-gps-lora-tracker-ip66 |
| xiao_nrf52840_ble | Seeed XIAO nRF52840 | 0x2886:0x0044 | https://www.seeedstudio.com/ |
| xiao_nrf52840_ble_sense | Seeed XIAO nRF52840 | 0x2886:0x0045 | https://www.seeedstudio.com/ |

## Internal app-preserving bootloader-update identities

These nRF52840 targets have no enabled SD/QSPI OTA store and use the internal `0x0A`
(`STAGE_CEILING|BOOT_UPDATE`) storage profile with the shared `0xED000` staging ceiling.
The target ID is the little-endian first 32 bits of SHA-256 over the complete 32-byte NUL-padded
`NRF_BL_%08X_<DEVICE_NAME>` field. `tools/check_internal_bootloader_targets.py` regenerates this inventory
from both build systems and fails on an unsafe target, noncanonical name, or collision.

| Board target | Manifest board ID | Exact DEVICE_NAME | Derived `.mota` target |
| --- | --- | --- | --- |
| gat562 | 0x239A0029 | GAT562_DFU | 0xD50D2D44 |
| heltec_mesh_pocket | 0x239A0071 | MESH_POCKET_OTA | 0x059277F4 |
| heltec_mesh_tower_v2 | 0x239A0071 | TOWER_V2_OTA | 0x1150F50E |
| heltec_t096 | 0x239A0071 | T096_DFU | 0x42354C85 |
| heltec_t1 | 0x239A0071 | T1_DFU | 0xFC556FFC |
| heltec_t114 | 0x239A0071 | T114_DFU | 0x0C3F2902 |
| keepteen_lt1 | 0x239A00B3 | KeepteenLT1_OTA | 0xDB2E7B51 |
| minewsemi_mx25le01 | 0x239A0029 | MX25_DFU | 0x026AA982 |
| promicro_nrf52840 | 0x239A00B3 | PROM_DFU | 0xAF79E8CC |
| t1000_e | 0x28860057 | T1KE_DFU | 0xE6F5F03F |
| thinknode_m3 | 0x239A00DA | TNM3_DFU | 0x0CA41DB2 |
| wiscore_rak3401 | 0x239A0029 | 3401_DFU | 0x23818A80 |
| wiscore_rak4631_board (including carrier aliases) | 0x239A0029 | 4631_DFU | 0x2D0DF000 |
| wismesh_tag | 0x239A0029 | RTAG_DFU | 0xC72E9C9C |

XIAO BLE/Sense retain their legacy QSPI identities and raw board-ID targets; they are intentionally not
part of this derived internal inventory.
