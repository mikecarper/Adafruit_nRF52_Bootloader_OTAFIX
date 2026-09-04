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

#include "usb_desc.h"

enum {
    STRID_LANGUAGE = 0 ,
    STRID_MANUFACTURER ,
    STRID_PRODUCT      ,
    STRID_SERIAL       ,
    STRID_CDC          ,
    STRID_MSC
};

// Serial is 64-bit DeviceID -> 16 chars len
static char desc_str_serial[1+16];

//--------------------------------------------------------------------+
// Device Descriptor
//--------------------------------------------------------------------+
tusb_desc_device_t desc_device =
{
    .bLength            = sizeof(tusb_desc_device_t),
    .bDescriptorType    = TUSB_DESC_DEVICE,
    .bcdUSB             = 0x0200,

    // Use Interface Association Descriptor (IAD) for CDC
    // As required by USB Specs IAD's subclass must be common class (2) and protocol must be IAD (1)
    .bDeviceClass       = TUSB_CLASS_MISC,
    .bDeviceSubClass    = MISC_SUBCLASS_COMMON,
    .bDeviceProtocol    = MISC_PROTOCOL_IAD,
    .bMaxPacketSize0    = CFG_TUD_ENDOINT0_SIZE,

    .idVendor           = USB_DESC_VID,
    .idProduct          = USB_DESC_UF2_PID,
    .bcdDevice          = 0x0100,

    .iManufacturer      = 0x01,
    .iProduct           = 0x02,
    .iSerialNumber      = 0x03,

    .bNumConfigurations = 0x01
};

// Invoked when received GET DEVICE DESCRIPTOR
// Application return pointer to descriptor
uint8_t const * tud_descriptor_device_cb(void)
{
  return (uint8_t const *) &desc_device;
}

//--------------------------------------------------------------------+
// Configuration Descriptor
//--------------------------------------------------------------------+

enum {
    ITF_NUM_CDC = 0  ,
    ITF_NUM_CDC_DATA ,
    ITF_NUM_MSC      ,
    ITF_NUM_TOTAL
};

#if CFG_TUD_MSC
#define USB_DESC_INTERFACE_COUNT ITF_NUM_TOTAL
#define USB_DESC_TOTAL_LEN       (TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN + TUD_MSC_DESC_LEN)
#else
#define USB_DESC_INTERFACE_COUNT (ITF_NUM_TOTAL - 1)
#define USB_DESC_TOTAL_LEN       (TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN)
#endif

uint8_t desc_configuration[] =
{
  // Interface count, string index, total length, attribute, power in mA
  TUD_CONFIG_DESCRIPTOR(1, USB_DESC_INTERFACE_COUNT, 0, USB_DESC_TOTAL_LEN, 0, 100),

  // Interface number, string index, EP notification address and size, EP data address (out, in) and size.
  TUD_CDC_DESCRIPTOR(ITF_NUM_CDC, STRID_CDC, 0x81, 8, 0x02, 0x82, 64),

#if CFG_TUD_MSC
  // Interface number, string index, EP Out & EP In address, EP size
  TUD_MSC_DESCRIPTOR(ITF_NUM_MSC, STRID_MSC, 0x03, 0x83, 64),
#endif
};


// Invoked when received GET CONFIGURATION DESCRIPTOR
// Application return pointer to descriptor
// Descriptor contents must exist long enough for transfer to complete
uint8_t const * tud_descriptor_configuration_cb(uint8_t index)
{
  (void) index; // for multiple configurations
  return desc_configuration;
}

// Enumerate as CDC + MSC or CDC only
void usb_desc_init(bool cdc_only)
{
#if CFG_TUD_MSC
  if ( cdc_only )
  {
    // The CDC prefix is itself a complete configuration descriptor. Shorten
    // the advertised descriptor instead of keeping a duplicate CDC-only copy.
    desc_configuration[2] = TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN;
    desc_configuration[4] = ITF_NUM_TOTAL - 1;

    // Change PID to CDC only
    desc_device.idProduct = USB_DESC_CDC_ONLY_PID;
  }
#else
  (void)cdc_only;
  desc_device.idProduct = USB_DESC_CDC_ONLY_PID;
#endif

  // Create Serial string descriptor
  uint8_t const* device_id = (uint8_t const*) &NRF_FICR->DEVICEID;

  for ( uint8_t i = 0; i < 8; i++ )
  {
    for ( uint8_t j = 0; j < 2; j++ )
    {
      uint8_t nibble = (device_id[i] >> (j * 4)) & 0xf;
      desc_str_serial[15 - (i * 2 + j)] =
          '0' + nibble + (((nibble + 6) >> 4) * 7); // memory is little endian
    }
  }
  desc_str_serial[16] = 0;
}

//--------------------------------------------------------------------+
// STRING DESCRIPTORS
//--------------------------------------------------------------------+

// array of pointer to string descriptors
char const* string_desc_arr [] =
{
  (const char[]) { 0x09, 0x04 }, // 0: is supported language is English (0x0409)
  BLEDIS_MANUFACTURER,           // 1: Manufacturer
  BLEDIS_MODEL,                  // 2: Product
  desc_str_serial,               // 3: Serials, should use chip ID
  "nRF Serial",                  // 4: CDC Interface
#if CFG_TUD_MSC
  "nRF UF2",                     // 5: MSC Interface
#endif
};

// up to 64 unicode characters
static uint16_t _desc_str[64+1];

// Invoked when received GET STRING DESCRIPTOR request
// Application return pointer to descriptor, whose contents must exist long enough for transfer to complete
uint16_t const* tud_descriptor_string_cb(uint8_t index, uint16_t langid)
{
  (void) langid;

  uint8_t chr_count;

  if ( index == STRID_LANGUAGE )
  {
    memcpy(&_desc_str[1], string_desc_arr[0], 2);
    chr_count = 1;
  }else
  {
    if ( !(index < sizeof(string_desc_arr)/sizeof(string_desc_arr[0])) ) return NULL;

    // Convert ASCII string into UTF-16
    const char* str = string_desc_arr[index];

    // Cap at max char
    chr_count = strlen(str);
    if ( chr_count > 31 ) chr_count = 31;

    for(uint8_t i=0; i<chr_count; i++)
    {
      _desc_str[1+i] = str[i];
    }
  }

  // first byte is length (including header), second byte is string type
  _desc_str[0] = (TUSB_DESC_STRING << 8 ) | (2*chr_count + 2);

  return _desc_str;
}
