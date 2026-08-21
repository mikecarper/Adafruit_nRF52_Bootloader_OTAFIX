/*
 * The MIT License (MIT)
 *
 * Copyright (c) 2026 Mike Carper
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

#ifndef USB_WAIT_H_
#define USB_WAIT_H_

#include <stdbool.h>
#include <stdint.h>

#ifndef DFU_USB_ENUMERATION_TIMEOUT_MS
#define DFU_USB_ENUMERATION_TIMEOUT_MS 30000u
#endif

#define DFU_SINGLE_TAP_TIMEOUT_MS 3000u

static inline uint32_t dfu_buttonless_timeout_ms(bool serial_only_dfu,
                                                 bool uf2_dfu) {
  // Explicit application requests (including a 1200-baud touch) get the full
  // host-enumeration window. The only fallback caller is MakeCode-style
  // single-tap recovery, which intentionally remains brief.
  return (serial_only_dfu || uf2_dfu) ? DFU_USB_ENUMERATION_TIMEOUT_MS
                                      : DFU_SINGLE_TAP_TIMEOUT_MS;
}

bool usb_wait_for_mount(uint32_t timeout_ms);

#endif
