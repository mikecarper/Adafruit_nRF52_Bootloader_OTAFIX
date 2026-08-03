#ifndef _HELTEC_MESH_TOWER_V2_SDCARD_H
#define _HELTEC_MESH_TOWER_V2_SDCARD_H

#include "../heltec_mesh_tower_v2/board.h"

// MeshTower V2 onboard microSD socket, Heltec partial reference circuit.
#define MOTA_SD_CARD     1
#define MOTA_SD_CS_PIN   _PINNUM(1, 0)
#define MOTA_SD_MOSI_PIN _PINNUM(1, 1)
#define MOTA_SD_SCK_PIN  _PINNUM(0, 6)
#define MOTA_SD_MISO_PIN _PINNUM(0, 26)

#endif
