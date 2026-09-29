#!/usr/bin/env python3
"""Render production recovery screens and check their bounds and information rows."""

import argparse
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BOARDS = ('heltec_t096', 'heltec_t114', 'heltec_t1')

HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "boards.h"
static unsigned calls;
static unsigned char pixels[DISPLAY_HEIGHT][DISPLAY_WIDTH];
void board_display_draw_line(int x, const uint8_t *data, int length) {
  assert(x == (int)calls && x < DISPLAY_WIDTH);
  assert(length == DISPLAY_HEIGHT * 2);
  calls++;
  for (int y = 0; y < DISPLAY_HEIGHT; ++y) {
    assert(data[y * 2] == data[y * 2 + 1]);
    assert(data[y * 2] == 0 || data[y * 2] == 255);
    pixels[y][x] = data[y * 2];
  }
}
void screen_draw_drag(void);
void screen_draw_ble(void);
static void save(const char *path) {
  assert(calls == DISPLAY_WIDTH);
  for (int row = 1; row <= 4; ++row) {
    unsigned lit = 0;
    int middle = DISPLAY_HEIGHT * row / 5;
    for (int y = middle - 8; y < middle + 8; ++y)
      for (int x = 0; x < DISPLAY_WIDTH; ++x) lit += pixels[y][x] != 0;
    assert(lit > 20);
  }
  FILE *file = fopen(path, "wb");
  assert(file);
  fprintf(file, "P5\n%d %d\n255\n", DISPLAY_WIDTH, DISPLAY_HEIGHT);
  assert(fwrite(pixels, 1, sizeof(pixels), file) == sizeof(pixels));
  assert(fclose(file) == 0);
}
int main(int argc, char **argv) {
  assert(argc == 3);
  screen_draw_drag();
  save(argv[1]);
  unsigned char usb[sizeof(pixels)];
  memcpy(usb, pixels, sizeof(usb));
  calls = 0;
  screen_draw_ble();
  save(argv[2]);
  assert(memcmp(usb, pixels, sizeof(usb)) != 0);
  // The model/version portion must survive either transport selection.
  assert(memcmp(usb, pixels, sizeof(pixels) / 2) == 0);
  return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render-dir', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        output = args.render_dir or work
        output.mkdir(parents=True, exist_ok=True)
        (work / 'harness.c').write_text(HARNESS, encoding='ascii')
        for board in BOARDS:
            header = ROOT / 'src/boards' / board / 'board.h'
            name = {'heltec_t096': 'T096_DFU', 'heltec_t114': 'T114_DFU',
                    'heltec_t1': 'T1_DFU'}[board]
            (work / 'boards.h').write_text(
                '#pragma once\n#include <stdbool.h>\n#include <stdint.h>\n'
                f'#include "{header}"\n'
                '#define UF2_VERSION_BASE "v0.11.0-OTAFIX2.4.10"\n'
                f'#define DEVICE_NAME "{name}"\n'
                'void board_display_draw_line(int, const uint8_t *, int);\n',
                encoding='ascii')
            binary = work / board
            sanitizers = ([] if os.name == 'nt' else
                          ['-fsanitize=address,undefined', '-fno-pie', '-no-pie'])
            subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-O1', '-g',
                            '-Wall', '-Wextra', '-Werror', *sanitizers,
                            '-DMOTA_INTERNAL_BOOTLOADER_UPDATE=1',
                            '-I', str(work), str(work / 'harness.c'),
                            str(ROOT / 'src/screen.c'), str(ROOT / 'src/images.c'),
                            '-o', str(binary)], check=True)
            subprocess.run([str(binary), str(output / f'{board}-usb.pgm'),
                            str(output / f'{board}-ble.pgm')], check=True)
    print('Recovery screens: all three boards and USB/BLE information rows PASS')


if __name__ == '__main__':
    main()
