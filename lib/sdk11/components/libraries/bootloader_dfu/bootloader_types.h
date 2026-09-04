/* Copyright (c) 2013 Nordic Semiconductor. All Rights Reserved.
 *
 * The information contained herein is property of Nordic Semiconductor ASA.
 * Terms and conditions of usage are described in detail in NORDIC
 * SEMICONDUCTOR STANDARD SOFTWARE LICENSE AGREEMENT.
 *
 * Licensees are granted free, non-transferable use of the information. NO
 * WARRANTY of ANY KIND is provided. This heading must NOT be removed from
 * the file.
 *
 */
 
/**@file
 *
 * @defgroup nrf_bootloader_types Types and definitions.
 * @{     
 *  
 * @ingroup nrf_bootloader
 * 
 * @brief Bootloader module type and definitions.
 */
 
#ifndef BOOTLOADER_TYPES_H__
#define BOOTLOADER_TYPES_H__

#include <stddef.h>
#include <stdint.h>

#define BOOTLOADER_DFU_START 0xB1

#define BOOTLOADER_SVC_APP_DATA_PTR_GET 0x02

/**@brief DFU Bank state code, which indicates wether the bank contains: A valid image, invalid image, or an erased flash.
  */
typedef enum
{
    BANK_VALID_APP   = 0x01,
    BANK_VALID_SD    = 0xA5,
    BANK_VALID_BOOT  = 0xAA,
    BANK_ERASED      = 0xFE,
    BANK_INVALID_APP = 0xFF,
} bootloader_bank_code_t;

/**@brief Structure holding bootloader settings for application and bank data.
 */
typedef struct
{
    uint16_t bank_0;          /**< Variable to store if bank 0 contains a valid application. */
    uint16_t bank_0_crc;      /**< If bank is valid, this field will contain a valid CRC of the total image. */
    uint16_t bank_1;          /**< Variable to store if bank 1 has been erased/prepared for new image. Bank 1 is only used in Banked Update scenario. */
    uint16_t format_version;  /**< Settings integrity format. This occupies legacy structure padding. */
    uint32_t bank_0_size;     /**< Size of active image in bank0 if present, otherwise 0. */
    uint32_t sd_image_size;   /**< Size of SoftDevice image in bank0 if bank_0 code is BANK_VALID_SD. */
    uint32_t bl_image_size;   /**< Size of Bootloader image in bank0 if bank_0 code is BANK_VALID_SD. */
    uint32_t app_image_size;  /**< Size of Application image in bank0 if bank_0 code is BANK_VALID_SD. */
    uint32_t sd_image_start;  /**< Location in flash where SoftDevice image is stored for SoftDevice update. */
    uint16_t record_crc;      /**< CRC-16 over all preceding fields. */
    uint16_t record_crc_inv;  /**< Bitwise inverse of record_crc, distinguishing it from erased legacy data. */
} bootloader_settings_t;

#define BOOTLOADER_SETTINGS_FORMAT_VERSION 1U

typedef char bootloader_settings_legacy_prefix_must_remain_28_bytes
    [(offsetof(bootloader_settings_t, record_crc) == 28) ? 1 : -1];
typedef char bootloader_settings_record_must_be_32_bytes
    [(sizeof(bootloader_settings_t) == 32) ? 1 : -1];

#endif // BOOTLOADER_TYPES_H__ 

/**@} */
