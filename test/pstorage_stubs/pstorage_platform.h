#ifndef PSTORAGE_PL_H__
#define PSTORAGE_PL_H__

#include <stdint.h>

#define PSTORAGE_FLASH_PAGE_SIZE 4096u
#define PSTORAGE_NUM_OF_PAGES    4u
#define PSTORAGE_CMD_QUEUE_SIZE  18u

typedef uint32_t pstorage_block_t;
typedef struct
{
    uint32_t module_id;
    pstorage_block_t block_id;
} pstorage_handle_t;
typedef uint32_t pstorage_size_t;

void pstorage_sys_event_handler(uint32_t sys_evt);

#endif
