/* Copyright (c) 2015 Nordic Semiconductor. All Rights Reserved.
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

#include "pstorage.h"
#include <stdlib.h>
#include <stdint.h>
#include "nordic_common.h"
#include "nrf_error.h"
#include "nrf_assert.h"
#include "nrf.h"
#include "nrf_soc.h"
#include "app_util.h"

/** @file
 *
 * @defgroup persistent_storage_raw Persistent Storage Interface - Raw Mode Implementation
 * @{
 * @ingroup persistent_storage
 * @brief Persistent Storage Interface - Raw Mode Implementation.
 *
 * @details This file contains the source code for raw mode implementation of pstorage.
 * It is intended for special use cases where flash size is critical or the application must have
 * full control of the flash, such as DFU. The registration function in this implementation only
 * allocates a module id for the queue but does not locate any flash pages for the registrant.
 * This implementation provides no safety checking of addresses when clearing or storing data into
 * flash. The application is responsible for handling flash addresses and care must therefore be
 * taken in application not to erase application area.
 * This implementation does not support the @ref pstorage_update function.
 */

#define INVALID_OPCODE              0x00    /**< Invalid op code identifier. */

#ifdef NRF51
  #define SOC_MAX_WRITE_SIZE          1024    /**< Maximum write size allowed for a single call to \ref sd_flash_write as specified in the SoC API on the nRF51. */
#elif defined(NRF52_SERIES)
  #define SOC_MAX_WRITE_SIZE          4096    /**< Maximum write size allowed for a single call to \ref sd_flash_write as specified in the SoC API on the nRF52. */
#else
  #error No target defined
#endif

#define PENDING_PACKET_SIZE         256     /**<  Maximum size of a single pending packet data buffer. */
#define PENDING_PACKET_COUNT        8       /**<  Maximum number of packets that can be buffered during lazy erase. */

#define FLASH_ACCESS_IDLE           0       /**< No flash request is active or waiting to be retried. */
#define FLASH_ACCESS_IN_FLIGHT      1       /**< A request issued by this module is in progress. */
#define FLASH_ACCESS_WAIT_BUSY      2       /**< A foreign request is in progress; retry ours after its event. */

#define CMD_FLAG_NONE               0x00    /**< Ordinary pstorage command. */
#define CMD_FLAG_LAZY_ERASE         0x01    /**< Erase owned by a buffered lazy store. */
#define CMD_FLAG_PENDING_STORE      0x02    /**< Store sourced from the pending-packet buffer. */

uint8_t  * dfu_page_erased;                                           /**< Pointer to page erased status array, set by DFU layer. */
uint32_t   dfu_image_page_count;                                      /**< Number of pages in DFU image, set by DFU layer. */
uint32_t   dfu_base_address;                                          /**< Base address for DFU image, set by DFU layer. */

static uint32_t lazy_erase_check_and_trigger(pstorage_handle_t * p_dest,
                                             pstorage_size_t size,
                                             pstorage_size_t offset);
static void process_pending_packets(void);
static void pending_packets_abort(uint32_t result);
static void cmd_queue_fail_head(uint32_t result);

/**
 * @brief Application registration information.
 *
 * @details Define application specific information that application needs to maintain to be able
 *          to process requests from each one of them.
 */
typedef struct
{
    pstorage_ntf_cb_t cb;   /**< Callback registered with the module to be notified of result of flash access.  */
} pstorage_module_table_t;


/**
 * @brief Defines command queue element.
 *
 * @details Defines command queue element. Each element encapsulates needed information to process
 *          a flash access command.
 */
typedef struct
{
    uint8_t              op_code;       /**< Identifies flash access operation being queued. Element is free is op-code is INVALID_OPCODE */
    uint8_t              flags;         /**< Internal ownership flags for lazy erase and buffered store commands. */
    pstorage_size_t      size;          /**< Identifies size in bytes requested for the operation. */
    pstorage_size_t      offset;        /**< Offset requested by the application for access operation. */
    pstorage_handle_t    storage_addr;  /**< Address/Identifier for persistent memory. */
    uint8_t            * p_data_addr;   /**< Address/Identifier for data memory. This is assumed to be resident memory. */
} cmd_queue_element_t;


/**
 * @brief Defines command queue, an element is free is op_code field is not invalid.
 *
 * @details Defines commands enqueued for flash access. At any point of time, this queue has one or
 *          more flash access operation pending if the count field is not zero. When the queue is
 *          not empty, the rp (read pointer) field points to the flash access command in progress
 *          or to requested next. The queue implements a simple first in first out algorithm.
 *          Data addresses are assumed to be resident.
 */
typedef struct
{
    uint8_t              rp;                              /**< Read pointer, pointing to flash access that is ongoing or to be requested next. */
    uint8_t              count;                           /**< Number of elements in the queue.  */
    uint8_t              flash_access;                    /**< Tracks whether an event is ours or only unblocks a retry. */
    cmd_queue_element_t  cmd[PSTORAGE_CMD_QUEUE_SIZE];    /**< Array to maintain flash access operation details */
}cmd_queue_t;

/**@brief Structure for buffering packets during lazy page erase. */
typedef struct
{
    bool                 valid;                                       /**< Whether this slot contains valid data. */
    pstorage_handle_t    handle;                                      /**< Storage handle for destination. */
    uint32_t             offset;                                      /**< Offset within the storage block. */
    uint32_t             size;                                        /**< Size of data in bytes. */
    uint8_t            * p_data_orig;                                 /**< Original data pointer for callback. */
    uint8_t              data[PENDING_PACKET_SIZE] __attribute__((aligned(4))); /**< Buffered packet data. */
} pending_packet_t;

static cmd_queue_t             m_cmd_queue;                           /**< Flash operation request queue. */
static pstorage_module_table_t m_app_table[PSTORAGE_NUM_OF_PAGES];    /**< Registered application information table. */
static pstorage_size_t         m_next_app_instance;                   /**< Points to the application module instance that can be allocated next */
static pstorage_size_t         m_round_val;                           /**< Round value for multiple round operations. For erase operations, the round value will contain current round counter which is identical to number of pages erased. For store operations, the round value contains current round of operation * SOC_MAX_WRITE_SIZE to ensure each store to the SoC Flash API is within the SoC limit. */

static pending_packet_t m_pending_packets[PENDING_PACKET_COUNT];      /**< Ring buffer for pending packets. */
static uint8_t          m_pending_read_idx;                           /**< Read index for pending packet ring buffer. */
static uint8_t          m_pending_write_idx;                          /**< Write index for pending packet ring buffer. */
static uint8_t          m_pending_count;                              /**< Number of pending packets in buffer. */
static bool             m_lazy_erase_active;                          /**< True if a lazy erase is in progress. */
static uint32_t         m_lazy_erase_page;                            /**< Page index currently being erased. */
static bool             m_processing_pending;                         /**< True if processing a pending packet store. */

/**
 * @brief Function for processing of commands and issuing flash access request to the SoftDevice.
 *
 * @return The return value received from SoftDevice.
 */
static uint32_t cmd_process(void);


/**
 * @brief Function for notifying application of any errors.
 *
 * @param[in] result Result of event being notified.
 * @param[in] p_elem Pointer to the element for which a notification should be given.
 */
static void app_notify(uint32_t result, cmd_queue_element_t * p_elem);


/**
 * @defgroup utility_functions Utility internal functions.
 * @{
 * @details Utility functions needed for interfacing with flash through SoC APIs.
 * SoC APIs are non blocking and provide the result of flash access through an event.
 *
 * @note Only one flash access operation is permitted at a time by SoC. Hence a queue is
 * maintained by this module.
 */

/**
 * @brief Function for initializing a command queue element.
 *
 * @param[in] index Index identifying element to be initialized.
 */
static void cmd_queue_element_init(uint32_t index)
{
    // Internal function and checks on range of index can be avoided
    m_cmd_queue.cmd[index].op_code                = INVALID_OPCODE;
    m_cmd_queue.cmd[index].flags                  = CMD_FLAG_NONE;
    m_cmd_queue.cmd[index].size                   = 0;
    m_cmd_queue.cmd[index].storage_addr.module_id = PSTORAGE_NUM_OF_PAGES;
    m_cmd_queue.cmd[index].storage_addr.block_id  = 0;
    m_cmd_queue.cmd[index].p_data_addr            = NULL;
    m_cmd_queue.cmd[index].offset                 = 0;
}


/**
 * @brief Function for initializing the command queue.
 */
static void cmd_queue_init(void)
{
    uint32_t cmd_index;

    m_round_val              = 0;
    m_cmd_queue.rp           = 0;
    m_cmd_queue.count        = 0;
    m_cmd_queue.flash_access = FLASH_ACCESS_IDLE;

    for(cmd_index = 0; cmd_index < PSTORAGE_CMD_QUEUE_SIZE; cmd_index++)
    {
        cmd_queue_element_init(cmd_index);
    }
}

/**
 * @brief Function for initializing the pending packets buffer.
 */
static void pending_packets_init(void)
{
    for (int i = 0; i < PENDING_PACKET_COUNT; i++)
    {
        m_pending_packets[i].valid = false;
    }
    m_pending_read_idx = 0;
    m_pending_write_idx = 0;
    m_pending_count = 0;
    m_lazy_erase_active = false;
    m_lazy_erase_page = 0;
    m_processing_pending = false;
}

/**
 * @brief Function for adding a packet to the pending buffer.
 *
 * @param[in] p_handle Pointer to the storage handle.
 * @param[in] p_data   Pointer to the data to buffer.
 * @param[in] size     Size of data in bytes.
 * @param[in] offset   Offset within the storage block.
 *
 * @retval true  If the packet was successfully added.
 * @retval false If the buffer is full or size exceeds maximum.
 */
static bool pending_packet_add(pstorage_handle_t * p_handle, uint8_t * p_data,
                               uint32_t size, uint32_t offset)
{
    if (m_pending_count >= PENDING_PACKET_COUNT || size > PENDING_PACKET_SIZE)
    {
        return false;
    }

    pending_packet_t * p = &m_pending_packets[m_pending_write_idx];
    p->handle = *p_handle;
    p->offset = offset;
    p->size = size;
    p->p_data_orig = p_data;
    memcpy(p->data, p_data, size);
    p->valid = true;

    m_pending_write_idx = (m_pending_write_idx + 1) % PENDING_PACKET_COUNT;
    m_pending_count++;

    return true;
}

/**
 * @brief Function for getting a pointer to the next pending packet without removing it.
 *
 * @return Pointer to the next pending packet, or NULL if buffer is empty.
 */
static pending_packet_t * pending_packet_peek(void)
{
    if (m_pending_count == 0)
    {
        return NULL;
    }
    return &m_pending_packets[m_pending_read_idx];
}

/**
 * @brief Function for removing the next pending packet from the buffer.
 */
static void pending_packet_pop(void)
{
    if (m_pending_count > 0)
    {
        m_pending_packets[m_pending_read_idx].valid = false;
        m_pending_read_idx = (m_pending_read_idx + 1) % PENDING_PACKET_COUNT;
        m_pending_count--;
    }
}

/**@brief Remove and return the command at the queue head before invoking its callback. */
static void cmd_queue_head_pop(cmd_queue_element_t * p_cmd)
{
    uint8_t queue_rp = m_cmd_queue.rp;

    *p_cmd = m_cmd_queue.cmd[queue_rp];
    cmd_queue_element_init(queue_rp);
    m_cmd_queue.count--;
    m_cmd_queue.rp++;
    if (m_cmd_queue.rp >= PSTORAGE_CMD_QUEUE_SIZE)
    {
        m_cmd_queue.rp -= PSTORAGE_CMD_QUEUE_SIZE;
    }
    m_round_val = 0;
}

/**
 * @brief Function for enqueueing a flash access operation.
 *
 * @param[in] opcode         Operation code for the command to queue.
 * @param[in] p_storage_addr Pointer to the destination address.
 * @param[in] p_data_addr    Pointer to the source address containing the data.
 * @param[in] size           Size of data clear or write.
 * @param[in] offset         Offset to the address identified by the source data address.
 * @param[in] flags          Internal ownership flags for buffered operations.
 *
 * @retval NRF_SUCCESS      If the enqueueing succeeded.
 * @retval NRF_ERROR_NO_MEM In case the queue is full.
 * @return Any error returned by the SoftDevice flash API.
 */
static uint32_t cmd_queue_enqueue(uint8_t             opcode,
                                  pstorage_handle_t * p_storage_addr,
                                  uint8_t           * p_data_addr,
                                  pstorage_size_t     size,
                                  pstorage_size_t     offset,
                                  uint8_t             flags)
{
    uint32_t retval;

    if (m_cmd_queue.count != PSTORAGE_CMD_QUEUE_SIZE)
    {
        bool queue_was_empty = (m_cmd_queue.count == 0);
        uint8_t write_index = m_cmd_queue.rp + m_cmd_queue.count;

        if (write_index >= PSTORAGE_CMD_QUEUE_SIZE)
        {
            write_index -= PSTORAGE_CMD_QUEUE_SIZE;
        }

        m_cmd_queue.cmd[write_index].op_code      = opcode;
        m_cmd_queue.cmd[write_index].flags        = flags;
        m_cmd_queue.cmd[write_index].p_data_addr  = p_data_addr;
        m_cmd_queue.cmd[write_index].storage_addr = (*p_storage_addr);
        m_cmd_queue.cmd[write_index].size         = size;
        m_cmd_queue.cmd[write_index].offset       = offset;
        m_cmd_queue.count++;
        retval                                    = NRF_SUCCESS;
        if (queue_was_empty && m_cmd_queue.flash_access == FLASH_ACCESS_IDLE)
        {
            retval = cmd_process();
            if (retval == NRF_ERROR_BUSY)
            {
                // In case of busy error code, it is possible to attempt to access flash.
                retval = NRF_SUCCESS;
            }
            else if (retval != NRF_SUCCESS)
            {
                // The caller has rejected this command synchronously. Do not leave it queued.
                m_cmd_queue.count--;
                cmd_queue_element_init(write_index);
                m_round_val = 0;
            }
        }
    }
    else
    {
        retval = NRF_ERROR_NO_MEM;
    }

    return retval;
}


/**
 * @brief Function for dequeueing a command element.
 *
 * @retval NRF_SUCCESS The next command was started, is waiting after BUSY, or the queue is empty.
 */
static uint32_t cmd_queue_dequeue(void)
{
    // Start the next accepted command. Fatal synchronous errors are reported to
    // that command's original caller and removed before advancing the queue.
    while ((m_cmd_queue.count > 0) && (m_cmd_queue.flash_access == FLASH_ACCESS_IDLE))
    {
        uint32_t retval = cmd_process();
        if (retval == NRF_SUCCESS || retval == NRF_ERROR_BUSY)
        {
            return NRF_SUCCESS;
        }

        cmd_queue_fail_head(retval);
    }

    if (m_cmd_queue.count == 0 && m_pending_count > 0 &&
        !m_processing_pending && !m_lazy_erase_active)
    {
        process_pending_packets();
    }

    return NRF_SUCCESS;
}


/**
 * @brief Function for notifying application of any errors.
 *
 * @param[in] result Result of event being notified.
 * @param[in] p_elem Pointer to the element for which a notification should be given.
 */
static void app_notify(uint32_t result, cmd_queue_element_t * p_elem)
{
    pstorage_ntf_cb_t ntf_cb;
    uint8_t           op_code = p_elem->op_code;

    if (p_elem->storage_addr.module_id < PSTORAGE_NUM_OF_PAGES)
    {
        ntf_cb = m_app_table[p_elem->storage_addr.module_id].cb;
        if (ntf_cb != NULL)
        {
            ntf_cb(&p_elem->storage_addr,
                   op_code,
                   result,
                   p_elem->p_data_addr,
                   p_elem->size);
        }
    }
}

/**
 * @brief Function for notifying application of buffered store completion.
 *
 * @param[in] result   Result of event being notified.
 * @param[in] p_handle Pointer to the storage handle.
 * @param[in] p_data   Pointer to the data buffer.
 * @param[in] size     Size of data in bytes.
 */
static void app_notify_buffered(uint32_t result, pstorage_handle_t * p_handle,
                                uint8_t * p_data, uint32_t size)
{
    if (p_handle->module_id < PSTORAGE_NUM_OF_PAGES)
    {
        pstorage_ntf_cb_t ntf_cb = m_app_table[p_handle->module_id].cb;
        if (ntf_cb != NULL)
        {
            ntf_cb(p_handle, PSTORAGE_STORE_OP_CODE, result, p_data, size);
        }
    }
}

/**@brief Fail every packet that was already accepted into the pending buffer. */
static void pending_packets_abort(uint32_t result)
{
    uint8_t packets_to_abort = m_pending_count;

    m_lazy_erase_active = false;
    m_lazy_erase_page = 0;
    m_processing_pending = false;

    while (packets_to_abort > 0 && m_pending_count > 0)
    {
        packets_to_abort--;
        pending_packet_t * p = pending_packet_peek();
        pstorage_handle_t cb_handle = p->handle;
        uint8_t * cb_data = p->p_data_orig;
        uint32_t cb_size = p->size;

        pending_packet_pop();
        app_notify_buffered(result, &cb_handle, cb_data, cb_size);
    }
}

/**@brief Remove a failed accepted command and notify its original owner exactly once. */
static void cmd_queue_fail_head(uint32_t result)
{
    cmd_queue_element_t failed_cmd;

    cmd_queue_head_pop(&failed_cmd);
    if ((failed_cmd.flags & (CMD_FLAG_LAZY_ERASE | CMD_FLAG_PENDING_STORE)) != 0)
    {
        pending_packets_abort(result);
    }
    else
    {
        app_notify(result, &failed_cmd);
    }
}

/**
 * @brief Function for processing packets from the pending buffer.
 *
 * @details Attempts to process the next pending packet. If the target page needs
 *          erasing, triggers a lazy erase. Otherwise enqueues the store operation.
 */
static void process_pending_packets(void)
{
    if (m_processing_pending || m_lazy_erase_active || m_cmd_queue.count > 0)
    {
        return;
    }

    pending_packet_t * p = pending_packet_peek();
    if (p == NULL)
    {
        return;
    }

    uint32_t ret = lazy_erase_check_and_trigger(&p->handle, p->size, p->offset);
    if (ret != NRF_SUCCESS)
    {
        pending_packets_abort(ret);
        // A callback may have accepted a new store behind the abort snapshot.
        // With no flash event left to drive the queue, start that work now.
        cmd_queue_dequeue();
        return;
    }

    // Check if this packet needs an erase first
    if (m_lazy_erase_active)
    {
        // Erase triggered, don't process this packet yet
        return;
    }

    // Page is ready, enqueue the store
    m_processing_pending = true;

    ret = cmd_queue_enqueue(PSTORAGE_STORE_OP_CODE, &p->handle, p->data,
                            p->size, p->offset, CMD_FLAG_PENDING_STORE);

    if (ret != NRF_SUCCESS)
    {
        pending_packets_abort(ret);
        // A callback may have accepted a new store behind the abort snapshot.
        // With no flash event left to drive the queue, start that work now.
        cmd_queue_dequeue();
    }
}


/**
 * @brief Function for checking and triggering lazy erase if needed.
 * @param[in]  p_dest Destination address where data is to be stored persistently.
 * @param[in]  size   Size of data to be stored expressed in bytes.
 * @param[in]  offset Offset in bytes to be applied when writing to the block.
 * @retval     NRF_SUCCESS       No erase was needed or a lazy erase was queued.
 * @return     Any error returned while enqueueing the lazy erase.
 */
static uint32_t lazy_erase_check_and_trigger(pstorage_handle_t * p_handle,
                                             pstorage_size_t size,
                                             pstorage_size_t offset)
{
    uint32_t target_addr = p_handle->block_id + offset;

    if (target_addr < dfu_base_address || dfu_page_erased == NULL)
    {
        return NRF_SUCCESS;
    }

    uint32_t rel_addr = target_addr - dfu_base_address;
    uint32_t page_index = rel_addr / PSTORAGE_FLASH_PAGE_SIZE;

    // Also check end of packet
    uint32_t end_addr = target_addr + size - 1;
    uint32_t end_rel_addr = end_addr - dfu_base_address;
    uint32_t end_page_index = end_rel_addr / PSTORAGE_FLASH_PAGE_SIZE;

    // Check if start page needs erase
    bool start_needs_erase = (page_index < dfu_image_page_count && !dfu_page_erased[page_index]);

    // Check if end page needs erase (and is different from start page)
    bool end_needs_erase = (end_page_index != page_index) &&
                           (end_page_index < dfu_image_page_count && !dfu_page_erased[end_page_index]);

    if (!start_needs_erase && !end_needs_erase)
    {
        return NRF_SUCCESS;
    }

    // Determine which page to erase (start page takes priority)
    uint32_t erase_page = start_needs_erase ? page_index : end_page_index;

    m_lazy_erase_active = true;
    m_lazy_erase_page = erase_page;

    pstorage_handle_t erase_handle;
    erase_handle.block_id = dfu_base_address + (erase_page * PSTORAGE_FLASH_PAGE_SIZE);
    erase_handle.module_id = p_handle->module_id;

    uint32_t ret = cmd_queue_enqueue(PSTORAGE_CLEAR_OP_CODE, &erase_handle, NULL,
                                     PSTORAGE_FLASH_PAGE_SIZE, 0, CMD_FLAG_LAZY_ERASE);
    if (ret != NRF_SUCCESS)
    {
        m_lazy_erase_active = false;
        return ret;
    }

    return NRF_SUCCESS;
}


/**
 * @brief Function for handling of system events from SoftDevice.
 *
 * @param[in] sys_evt System event received.
 */
void pstorage_sys_event_handler(uint32_t sys_evt)
{
    // Do not bother processing events we are not interested in
    if (sys_evt != NRF_EVT_FLASH_OPERATION_SUCCESS &&
        sys_evt != NRF_EVT_FLASH_OPERATION_ERROR) return;

    uint32_t retval = NRF_SUCCESS;

    // A BUSY return means this event belongs to the preceding flash request.
    // It only makes the queue retryable; it must not complete our queue head.
    if (m_cmd_queue.flash_access == FLASH_ACCESS_WAIT_BUSY)
    {
        m_cmd_queue.flash_access = FLASH_ACCESS_IDLE;
        cmd_queue_dequeue();
        return;
    }

    // The event shall only be processed if requested by this module.
    if (m_cmd_queue.flash_access == FLASH_ACCESS_IN_FLIGHT)
    {
        cmd_queue_element_t * p_cmd;
        m_cmd_queue.flash_access = FLASH_ACCESS_IDLE;
        switch (sys_evt)
        {
            case NRF_EVT_FLASH_OPERATION_SUCCESS:
            {
                p_cmd = &m_cmd_queue.cmd[m_cmd_queue.rp];
                m_round_val++;

                bool command_finished = ((m_round_val * SOC_MAX_WRITE_SIZE) >= p_cmd->size);

                if (command_finished)
                {
                    cmd_queue_element_t completed_cmd;
                    cmd_queue_head_pop(&completed_cmd);

                    if ((completed_cmd.flags & CMD_FLAG_LAZY_ERASE) != 0)
                    {
                        // Lazy erase completed
                        if (dfu_page_erased != NULL && m_lazy_erase_page < dfu_image_page_count)
                        {
                            dfu_page_erased[m_lazy_erase_page] = 1;
                        }

                        m_lazy_erase_active = false;

                        process_pending_packets();
                    }
                    else if ((completed_cmd.flags & CMD_FLAG_PENDING_STORE) != 0)
                    {
                        // Store from pending buffer completed
                        pending_packet_t * p = pending_packet_peek();
                        if (p != NULL)
                        {
                            pstorage_handle_t cb_handle = p->handle;
                            uint8_t* cb_data = p->p_data_orig;
                            uint32_t cb_size = p->size;

                            pending_packet_pop();

                            // Clear flag BEFORE callback
                            m_processing_pending = false;

                            // Notify application that buffered this buffered store is done
                            app_notify_buffered(retval, &cb_handle, cb_data, cb_size);
                        }
                        else
                        {
                            m_processing_pending = false;
                        }
                    }
                    else
                    {
                        app_notify(retval, &completed_cmd);
                    }
                }

                // Process next queued command OR next pending packet
                if (m_cmd_queue.count > 0)
                {
                    cmd_queue_dequeue();
                }
                else if (m_pending_count > 0 && !m_processing_pending && !m_lazy_erase_active)
                {
                    // Queue is empty but we have pending packets - process one
                    process_pending_packets();
                }
            }
            break;

            case NRF_EVT_FLASH_OPERATION_ERROR:
                cmd_queue_fail_head(NRF_ERROR_TIMEOUT);
                cmd_queue_dequeue();
                break;

            default:
                // No implementation needed.
                break;
        }
    }
}


/**
 * @brief Function for processing of commands and issuing flash access request to the SoftDevice.
 *
 * @return The return value received from SoftDevice.
 * @remark This function is only called when m_cmd_queue.flash_access == FLASH_ACCESS_IDLE
 */
static uint32_t cmd_process(void)
{
    uint32_t              retval;
    uint32_t              storage_addr;
    cmd_queue_element_t * p_cmd;

    retval = NRF_ERROR_FORBIDDEN;

    if (m_cmd_queue.count == 0)
    {
        return NRF_SUCCESS;
    }

    p_cmd = &m_cmd_queue.cmd[m_cmd_queue.rp];

    storage_addr = p_cmd->storage_addr.block_id;

    // Let's assume we will do a flash access
    m_cmd_queue.flash_access = FLASH_ACCESS_IN_FLIGHT;

    switch (p_cmd->op_code)
    {
        case PSTORAGE_STORE_OP_CODE:
        {
            uint32_t  size;
            uint32_t  offset;
            uint8_t * p_data_addr = p_cmd->p_data_addr;

            offset        = (m_round_val * SOC_MAX_WRITE_SIZE);
            size          = p_cmd->size - offset;
            p_data_addr  += offset;
            storage_addr += (p_cmd->offset + offset);

            if (size < SOC_MAX_WRITE_SIZE)
            {
                retval = sd_flash_write(((uint32_t *)storage_addr),
                                        (uint32_t *)p_data_addr,
                                        size / sizeof(uint32_t));
            }
            else
            {
                retval = sd_flash_write(((uint32_t *)storage_addr),
                                        (uint32_t *)p_data_addr,
                                        SOC_MAX_WRITE_SIZE / sizeof(uint32_t));
            }
        }
        break;

        case PSTORAGE_CLEAR_OP_CODE:
        {
            uint32_t page_number;

            page_number =  ((storage_addr / PSTORAGE_FLASH_PAGE_SIZE) +
                            m_round_val);

            retval = sd_flash_page_erase(page_number);
        }
        break;

        default:
            // Should never reach here.
            break;
    }

    // An error means we will not do it
    if (retval == NRF_ERROR_BUSY)
    {
       m_cmd_queue.flash_access = FLASH_ACCESS_WAIT_BUSY;
    }
    else if (retval != NRF_SUCCESS)
    {
       m_cmd_queue.flash_access = FLASH_ACCESS_IDLE;
    }

    return retval;
}
/** @} */


uint32_t pstorage_init(void)
{
    cmd_queue_init();
    pending_packets_init();

    m_next_app_instance = 0;
    m_round_val         = 0;

    for(unsigned int index = 0; index < PSTORAGE_NUM_OF_PAGES; index++)
    {
        m_app_table[index].cb          = NULL;
    }

    return NRF_SUCCESS;
}


uint32_t pstorage_register(pstorage_module_param_t * p_module_param,
                           pstorage_handle_t       * p_block_id)
{
    if (m_next_app_instance == PSTORAGE_NUM_OF_PAGES)
    {
        return NRF_ERROR_NO_MEM;
    }

    p_block_id->module_id                 = m_next_app_instance;
    m_app_table[m_next_app_instance++].cb = p_module_param->cb;

    return NRF_SUCCESS;
}


uint32_t pstorage_block_identifier_get(pstorage_handle_t * p_base_id,
                                       pstorage_size_t     block_num,
                                       pstorage_handle_t * p_block_id)
{
    return NRF_ERROR_NOT_SUPPORTED;
}


uint32_t pstorage_store(pstorage_handle_t * p_dest,
                        uint8_t           * p_src,
                        pstorage_size_t     size,
                        pstorage_size_t     offset)
{
    // Verify word alignment.
    if ((!is_word_aligned(p_src)) || (!is_word_aligned((void *)(p_dest->block_id + offset))))
    {
        return NRF_ERROR_INVALID_ADDR;
    }

    // Once a buffered packet has been accepted, every later store must join
    // the same pending FIFO until it drains. Otherwise a store received while
    // the head packet is in flight can enter the command queue directly and
    // overtake older buffered packets.
    if (m_lazy_erase_active || m_processing_pending || m_pending_count > 0)
    {
        if (!pending_packet_add(p_dest, p_src, size, offset))
        {
            return NRF_ERROR_NO_MEM;
        }
        return NRF_SUCCESS;
    }

    if (!m_lazy_erase_active)
    {
        uint32_t ret = lazy_erase_check_and_trigger(p_dest, size, offset);
        if (ret != NRF_SUCCESS)
        {
            return ret;
        }
    }

    if (m_lazy_erase_active)
    {
        // Buffer this packet - erase in progress or just triggered
        if (!pending_packet_add(p_dest, p_src, size, offset))
        {
            return NRF_ERROR_NO_MEM;
        }
        return NRF_SUCCESS;
    }

    // Page already erased, proceed with store
    return cmd_queue_enqueue(PSTORAGE_STORE_OP_CODE, p_dest, p_src, size,
                             offset, CMD_FLAG_NONE);
}


uint32_t pstorage_clear(pstorage_handle_t * p_dest, pstorage_size_t size)
{
    // A lazy erase and its buffered stores form one accepted FIFO sequence.
    // Do not accept a later clear into the ordinary command queue, where it
    // would otherwise run before those older stores. The caller can retry as
    // soon as the pending FIFO has drained.
    if (m_lazy_erase_active || m_processing_pending || m_pending_count > 0)
    {
        return NRF_ERROR_NO_MEM;
    }

    return cmd_queue_enqueue(PSTORAGE_CLEAR_OP_CODE, p_dest, NULL, size, 0,
                             CMD_FLAG_NONE);
}


/**
 * @}
 */
