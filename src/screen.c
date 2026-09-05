/*
 * The MIT License (MIT)
 *
 * Copyright (c) 2020 Ha Thach (tinyusb.org) for Adafruit Industries
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 */

#include "boards.h"

#if defined(DISPLAY_PIN_SCK)

  #ifndef BANNER_TEXT
    #define BANNER_TEXT "made by oltaco / github.com/oltaco"
  #endif // BANNER_TEXT

  #include <stdlib.h>
  #include <string.h>

  // Cursor advance and rendered width for a glyph at an arbitrary scale.
  #define CHAR_ADV(size)          (5 * (size) + 1)
  #define CHAR_INK(size)          (6 * (size))
  #define TEXT_WIDTH(size, count) ((count) ? CHAR_ADV(size) * ((count) - 1) + CHAR_INK(size) : 0)

  #define COL0(r, g, b)           ((((r) >> 3) << 11) | (((g) >> 2) << 5) | ((b) >> 3))
  #define COL(c)                  COL0((c >> 16) & 0xff, (c >> 8) & 0xff, c & 0xff)

#if defined(MOTA_INTERNAL_BOOTLOADER_UPDATE)
enum {
  COLOR_BLACK = 0,
  COLOR_WHITE = 1,
};

const uint16_t palette[] = {
  COL(0x000000),
  COL(0xffffff),
};
#else
enum {
  COLOR_BLACK  = 0,
  COLOR_WHITE  = 1,
  COLOR_RED    = 2,
  COLOR_PINK   = 3,
  COLOR_ORANGE = 4,
  COLOR_YELLOW = 5,
  COLOR_CYAN   = 6,
  COLOR_GREEN  = 7,
  COLOR_BLUE   = 8,
  COLOR_AQUA   = 9,
  COLOR_PURPLE = 10,
};

// 16-bit 565 color from 24-bit 888 format
const uint16_t palette[] = {
  COL(0x000000), // 0
  COL(0xffffff), // 1
  COL(0xff2121), // 2
  COL(0xff93c4), // 3
  COL(0xff8135), // 4
  COL(0xfff609), // 5
  COL(0x249ca3), // 6
  COL(0x78dc52), // 7
  COL(0x003fad), // 8
  COL(0x87f2ff), // 9
  COL(0x8e2ec4), // 10

  COL(0xa4839f), // 11
  COL(0x5c406c), // 12
  COL(0xe5cdc4), // 13
  COL(0x91463d), // 14
  COL(0x000000), // 15
};
#endif

  // The defaults preserve the 240x135 ST7789 layout. Smaller displays override
  // only the coordinates that differ in their board definition.
  #ifndef SCREEN_BAR1_Y
    #define SCREEN_BAR1_Y 0
  #endif
  #ifndef SCREEN_BAR1_H
    #define SCREEN_BAR1_H 52
  #endif
  #ifndef SCREEN_BAR2_Y
    #define SCREEN_BAR2_Y 52
  #endif
  #ifndef SCREEN_BAR2_H
    #define SCREEN_BAR2_H 55
  #endif
  #ifndef SCREEN_BAR3_Y
    #define SCREEN_BAR3_Y 107
  #endif
  #ifndef SCREEN_BAR3_H
    #define SCREEN_BAR3_H 14
  #endif
  #ifndef SCREEN_FILE_LOGO_X
    #define SCREEN_FILE_LOGO_X 0
  #endif
  #ifndef SCREEN_ARROW_LOGO_X
    #define SCREEN_ARROW_LOGO_X 65
  #endif
  #ifndef SCREEN_PENDRIVE_LOGO_X
    #define SCREEN_PENDRIVE_LOGO_X 129
  #endif
  #ifndef SCREEN_TITLE_Y
    #define SCREEN_TITLE_Y 5
  #endif
  #ifndef SCREEN_VERSION_Y
    #define SCREEN_VERSION_Y 40
  #endif
  #ifndef SCREEN_BANNER_Y
    #define SCREEN_BANNER_Y 110
  #endif
  #ifndef SCREEN_BLE_OTA_Y
    #define SCREEN_BLE_OTA_Y 65
  #endif
  #ifndef SCREEN_LARGE_FONT_SIZE
    #define SCREEN_LARGE_FONT_SIZE 4
  #endif
  #ifndef SCREEN_DRAG_Y
    #define SCREEN_DRAG_Y 70
  #endif
  #ifndef SCREEN_DRAG_X
    #define SCREEN_DRAG_X 47
  #endif

// TODO only buffer partial screen to save SRAM
// ESP32s2 can only statically allocated DRAM up to 160KB.
// the remaining 160KB can only be allocated at runtime as heap.
static uint8_t frame_buf[DISPLAY_WIDTH * DISPLAY_HEIGHT];
// static uint8_t* frame_buf;

extern const uint8_t font8[];
extern const uint8_t fileLogo[];
extern const uint8_t pendriveLogo[];
extern const uint8_t arrowLogo[];

#if !defined(MOTA_INTERNAL_BOOTLOADER_UPDATE)
//--------------------------------------------------------------------+
//
//--------------------------------------------------------------------+

// Print one character at an arbitrary integer scale.
static void printch(int x, int y, int color, const uint8_t *fnt, int size) {
  if (size <= 0 || x < 0 || y < 0 || x + CHAR_INK(size) > DISPLAY_WIDTH || y + 8 * size > DISPLAY_HEIGHT) {
    return;
  }

  for (int i = 0; i < CHAR_INK(size); ++i) {
    uint8_t      *p    = frame_buf + (x + i) * DISPLAY_HEIGHT + y;
    const uint8_t bits = fnt[i / size];
    for (int j = 0; j < 8; ++j) {
      if (bits & (1u << j)) {
        memset(p, color, (size_t)size);
      }
      p += size;
    }
  }
}

// print icon
static void printicon(int x, int y, int color, const uint8_t *icon) {
  int w  = *icon++;
  int h  = *icon++;
  int sz = *icon++;

  uint8_t mask   = 0x80;
  int     runlen = 0;
  int     runbit = 0;
  uint8_t lastb  = 0x00;

  for (int i = 0; i < w; ++i) {
    for (int j = 0; j < h; ++j) {
      int c = 0;
      if (mask != 0x80) {
        if (lastb & mask) {
          c = 1;
        }
        mask <<= 1;
      } else if (runlen) {
        if (runbit) {
          c = 1;
        }
        runlen--;
      } else {
        if (sz-- <= 0) {
          // TU_LOG1("Screen Panic code = 10");
        }
        lastb = *icon++;
        if (lastb & 0x80) {
          runlen = lastb & 63;
          runbit = lastb & 0x40;
        } else {
          mask = 0x01;
        }
        --j;
        continue; // restart
      }
      if (c && x + i >= 0 && x + i < DISPLAY_WIDTH && y + j >= 0 && y + j < DISPLAY_HEIGHT) {
        frame_buf[(x + i) * DISPLAY_HEIGHT + y + j] = color;
      }
    }
  }
}

static void print(int x, int y, int color, const char *text, int size) {
  if (size <= 0) {
    return;
  }

  int x0 = x;
  while (*text) {
    char c = *text++;
    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      x = x0;
      y += 8 * size + 2;
      continue;
    }
    if (x < 0 || y < 0 || x + CHAR_INK(size) > DISPLAY_WIDTH || y + 8 * size > DISPLAY_HEIGHT) {
      return;
    }
    if (c < ' ' || c >= 0x7f) {
      c = '?';
    }
    c -= ' ';
    printch(x, y, color, &font8[(int)c * 6], size);
    x += CHAR_ADV(size);
  }
}

static void print_centered(int y, int color, const char *text, int size) {
  const int count = (int)strlen(text);
  const int x     = (DISPLAY_WIDTH - TEXT_WIDTH(size, count)) / 2;
  print(x >= 0 ? x : 0, y, color, text, size);
}
#endif

//--------------------------------------------------------------------+
//
//--------------------------------------------------------------------+

static void draw_screen(const uint8_t *fb) {
  const uint8_t *p = fb;
  for (int y = 0; y < DISPLAY_WIDTH; ++y) {
    uint8_t  cc[DISPLAY_HEIGHT * 2];
    uint32_t dst = 0;
    for (int x = 0; x < DISPLAY_HEIGHT; ++x) {
      uint16_t color = palette[*p++ & 0xf];
      cc[dst++]      = color >> 8;
      cc[dst++]      = color & 0xff;
    }

    board_display_draw_line(y, cc, sizeof(cc));
  }
}

#if defined(MOTA_INTERNAL_BOOTLOADER_UPDATE)
// Draw a compact block "DFU" mark without pulling the font/icon renderer into
// the space-constrained internal-update bootloader. Each byte describes one
// five-cell-tall column; zero columns separate the letters.
static __attribute__((noinline)) void draw_dfu(void) {
  static const uint8_t columns[] = {
    0x1f, 0x11, 0x0e, 0x00, // D
    0x1f, 0x05, 0x01, 0x00, // F
    0x1f, 0x10, 0x1f,       // U
  };
  enum {
    CELL = DISPLAY_HEIGHT / 7,
    LEFT = (DISPLAY_WIDTH - (int)sizeof(columns) * CELL) / 2,
    TOP  = (DISPLAY_HEIGHT - 5 * CELL) / 2,
  };

  for (unsigned column = 0; column < sizeof(columns); ++column) {
    for (int x = 0; x < CELL; ++x) {
      uint8_t *p = frame_buf + (LEFT + (int)column * CELL + x) * DISPLAY_HEIGHT + TOP;
      for (unsigned row = 0; row < 5; ++row) {
        if (columns[column] & (1u << row)) {
          memset(p + row * CELL, COLOR_WHITE, CELL);
        }
      }
    }
  }

  draw_screen(frame_buf);
}
#endif

// Draw a color bar, clipping a malformed board-specific layout to the buffer.
#if !defined(MOTA_INTERNAL_BOOTLOADER_UPDATE)
static void draw_bar(int y, int h, int color) {
  if (y < 0) {
    h += y;
    y = 0;
  }
  if (h <= 0 || y >= DISPLAY_HEIGHT) {
    return;
  }
  if (h > DISPLAY_HEIGHT - y) {
    h = DISPLAY_HEIGHT - y;
  }

  for (int x = 0; x < DISPLAY_WIDTH; ++x) {
    memset(frame_buf + x * DISPLAY_HEIGHT + y, color, h);
  }
}
#endif

// draw drag & drop screen
void screen_draw_drag(void) {
#if defined(MOTA_INTERNAL_BOOTLOADER_UPDATE)
  draw_dfu();
#else
  draw_bar(SCREEN_BAR1_Y, SCREEN_BAR1_H, COLOR_GREEN);
  draw_bar(SCREEN_BAR2_Y, SCREEN_BAR2_H, COLOR_BLUE);
  draw_bar(SCREEN_BAR3_Y, SCREEN_BAR3_H, COLOR_ORANGE);

  print_centered(SCREEN_TITLE_Y, COLOR_WHITE, DISPLAY_TITLE, SCREEN_LARGE_FONT_SIZE);
  print_centered(SCREEN_VERSION_Y, COLOR_PURPLE, UF2_VERSION_BASE, 1);
  print_centered(SCREEN_BANNER_Y, COLOR_WHITE, BANNER_TEXT, 1);

  printicon(SCREEN_DRAG_X + SCREEN_FILE_LOGO_X, SCREEN_DRAG_Y + 5, COLOR_WHITE, fileLogo);
  printicon(SCREEN_DRAG_X + SCREEN_ARROW_LOGO_X, SCREEN_DRAG_Y, COLOR_WHITE, arrowLogo);
  printicon(SCREEN_DRAG_X + SCREEN_PENDRIVE_LOGO_X, SCREEN_DRAG_Y, COLOR_WHITE, pendriveLogo);
  #ifndef SCREEN_HIDE_LABELS
  print(22, SCREEN_DRAG_Y - 12, COLOR_WHITE, "firmware.uf2", 1);
  print(160, SCREEN_DRAG_Y - 12, COLOR_WHITE, UF2_VOLUME_LABEL, 1);
  #endif

  draw_screen(frame_buf);
#endif
}

void screen_draw_ble(void) {
#if defined(MOTA_INTERNAL_BOOTLOADER_UPDATE)
  draw_dfu();
#else
  draw_bar(SCREEN_BAR1_Y, SCREEN_BAR1_H, COLOR_GREEN);
  draw_bar(SCREEN_BAR2_Y, SCREEN_BAR2_H, COLOR_BLUE);
  draw_bar(SCREEN_BAR3_Y, SCREEN_BAR3_H, COLOR_ORANGE);

  print_centered(SCREEN_TITLE_Y, COLOR_WHITE, DISPLAY_TITLE, SCREEN_LARGE_FONT_SIZE);
  print_centered(SCREEN_VERSION_Y, COLOR_PURPLE, UF2_VERSION_BASE, 1);
  print_centered(SCREEN_BLE_OTA_Y, COLOR_WHITE, "BLE OTA", SCREEN_LARGE_FONT_SIZE);
  print_centered(SCREEN_BANNER_Y, COLOR_WHITE, BANNER_TEXT, 1);

  draw_screen(frame_buf);
#endif
}

#endif
