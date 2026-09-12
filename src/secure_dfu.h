// Experimental Nordic Secure DFU wire protocol. Application-only, unsigned
// packages with mandatory SHA-256. Resume is within the same powered DFU session.
// This is NOT a signed-firmware trust policy or a persistent recovery journal.
#ifndef OTAFIX_SECURE_DFU_H
#define OTAFIX_SECURE_DFU_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SECURE_DFU_COMMAND_MAX 256u
#define SECURE_DFU_OBJECT_MAX  4096u
#define SECURE_DFU_HW_VERSION  0x3401u

typedef struct {
  uint32_t size;
  uint8_t  sha256[32]; // Conventional SHA-256 byte order (wire hash is reversed).
} secure_dfu_image_t;

typedef struct {
  uint8_t            command[SECURE_DFU_COMMAND_MAX];
  uint32_t           data[SECURE_DFU_OBJECT_MAX / 4];
  secure_dfu_image_t image;
  uint32_t           command_size, command_offset, command_crc;
  uint32_t           committed, committed_crc, object_size, object_offset, data_crc;
  uint16_t           prn, prn_count;
  uint8_t            selected;
  bool               initialized, executed, completed, failed;
} secure_dfu_t;

// Responses contain the standard 0x60/opcode/status header (maximum 15 bytes).
// The caller must deliver the final successful EXECUTE response before reboot.
void   secure_dfu_init(secure_dfu_t *s);
size_t secure_dfu_control(secure_dfu_t *s, const uint8_t *in, size_t len, uint8_t out[15]);
size_t secure_dfu_packet(secure_dfu_t *s, const uint8_t *in, size_t len, uint8_t out[15]);
bool   secure_dfu_parse_command(const uint8_t *data, size_t len, uint32_t max_image, uint16_t fwid,
                                secure_dfu_image_t *image);

// Platform hooks: begin only after complete metadata validation; write returns
// only after the entire object is durable; finish verifies SHA-256 and vectors.
uint32_t secure_dfu_max_image(void);
uint16_t secure_dfu_fwid(void);
bool     secure_dfu_begin(const secure_dfu_image_t *image);
bool     secure_dfu_write(const uint32_t *data, uint32_t length);
bool     secure_dfu_finish(void);
void     secure_dfu_activity(void);

#endif
