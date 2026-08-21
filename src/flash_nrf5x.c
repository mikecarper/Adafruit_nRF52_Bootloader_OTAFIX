/*
 * The MIT License (MIT)
 *
 * Copyright (c) 2018 Ha Thach for Adafruit Industries
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

#include <string.h>
#include "nrf_sdm.h"
#include "nrf_wdt.h"
#include "flash_nrf5x.h"
#include "boards.h"
#include "dfu_types.h"

#define FLASH_CACHE_INVALID_ADDR  0xffffffff

static uint32_t _fl_addr = FLASH_CACHE_INVALID_ADDR;
static uint8_t _fl_buf[CODE_PAGE_SIZE] __attribute__((aligned(4)));

static void inherited_watchdog_feed(void)
{
    if (nrf_wdt_started(NRF_WDT))
    {
        uint32_t const enabled_channels = NRF_WDT->RREN & 0xffU;
        for (uint8_t channel = 0; channel < 8; channel++)
        {
            if (enabled_channels & (1U << channel))
            {
                nrf_wdt_reload_request_set(NRF_WDT, channel);
            }
        }
    }
}

void flash_nrf5x_discard(void)
{
    // An interrupted bootloader UF2 can leave an unflushed staging page in the
    // RAM cache. A new MSC session must reload that page after erasing it rather
    // than merge the new image with bytes from the abandoned transfer.
    _fl_addr = FLASH_CACHE_INVALID_ADDR;
}

void flash_nrf5x_erase (uint32_t dst, uint32_t len)
{
    uint32_t page_addr = dst & ~(CODE_PAGE_SIZE - 1);
    uint32_t const page_count = NRFX_CEIL_DIV(len, CODE_PAGE_SIZE);
    for ( uint32_t i = 0; i < page_count; i++ )
    {
        uint32_t const addr = page_addr + i * CODE_PAGE_SIZE;
        PRINTF("Erase 0x%08lX\r\n", addr);
        inherited_watchdog_feed();
        nrfx_nvmc_page_erase(addr);
        inherited_watchdog_feed();
    }
}

void flash_nrf5x_invalidate_app_settings(void)
{
    // bank_0 and bank_0_crc occupy the first settings word. Clearing that word
    // is a fast, one-way fail-closed transition from every stored state; the
    // completed UF2 update later erases and rewrites the full settings page.
    nrfx_nvmc_word_write(BOOTLOADER_SETTINGS_ADDRESS, 0);
    inherited_watchdog_feed();
}


void flash_nrf5x_flush (bool need_erase)
{
    if ( _fl_addr == FLASH_CACHE_INVALID_ADDR )
        return;

    // skip the write if contents matches
    if ( memcmp(_fl_buf, (void *) _fl_addr, CODE_PAGE_SIZE) != 0 )
    {
        // - nRF52832 dfu via uart can miss incoming byte when erasing because cpu is blocked for > 2ms.
        // Since dfu_prepare_func_app_erase() already erase the page for us, we can skip it here.
        // - nRF52840 dfu serial/uf2 are USB-based which are DMA and should have no problems.
        //
        // Note: MSC uf2 does not erase page in advance like dfu serial
        if ( need_erase )
        {
            PRINTF("Erase and ");
            inherited_watchdog_feed();
            nrfx_nvmc_page_erase(_fl_addr);
            inherited_watchdog_feed();
        }

        PRINTF("Write 0x%08lX\r\n", _fl_addr);
        for (uint32_t offset = 0; offset < CODE_PAGE_SIZE; offset += 256)
        {
            nrfx_nvmc_words_write(_fl_addr + offset, _fl_buf + offset, 256 / sizeof(uint32_t));
            inherited_watchdog_feed();
        }
    }

    _fl_addr = FLASH_CACHE_INVALID_ADDR;
}

void flash_nrf5x_write (uint32_t dst, void const *src, uint32_t len, bool need_erase)
{
    // While something to write...
    while (len > 0) {

        // Align to start of page
        uint32_t page_addr = dst & ~(CODE_PAGE_SIZE - 1);

        // If page changed, write modified contents
        if ( page_addr != _fl_addr )
        {
            flash_nrf5x_flush(need_erase);

            // Remember new page
            _fl_addr = page_addr;

            // And read its contents
            memcpy(_fl_buf, (void *) page_addr, CODE_PAGE_SIZE);
        }

        // Compute the write offset into the current page
        uint32_t offset_in_page = dst & (CODE_PAGE_SIZE - 1);

        // Compute how many bytes remaining to complete the page
        uint32_t bytes_to_end = CODE_PAGE_SIZE - offset_in_page;

        // Limit the count to the available bytes in the current page
        uint32_t max_bytes = bytes_to_end < len ? bytes_to_end : len;

        // Copy contents to our buffer
        memcpy(_fl_buf + offset_in_page, src, max_bytes);

        // Update variables
        len -= max_bytes;
        dst += max_bytes;
        src  = (void const *) ((uint8_t*)src + max_bytes);
    };
}

void flash_nrf5x_write_erased(uint32_t dst, void const *src, uint32_t len)
{
    // UF2 payloads are word-aligned and exactly 256 bytes. Program them as
    // individual blocks after their page has been erased in a prior callback;
    // keeping each NVMC write short bounds USB interrupt latency.
    nrfx_nvmc_words_write(dst, src, len / sizeof(uint32_t));
    inherited_watchdog_feed();
}
