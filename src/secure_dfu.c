#include "secure_dfu.h"
#include <string.h>

enum {
  CREATE   = 1,
  SET_PRN  = 2,
  CHECKSUM = 3,
  EXECUTE  = 4,
  SELECT   = 6
};
enum {
  COMMAND = 1,
  DATA    = 2
};
enum {
  OK            = 1,
  NOT_SUPPORTED = 2,
  BAD_PARAMETER = 3,
  BAD_OBJECT    = 5,
  BAD_TYPE      = 7,
  NOT_PERMITTED = 8,
  FAILED        = 10
};

static uint32_t get32(const uint8_t *p) {
  return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static void put32(uint8_t *p, uint32_t n) {
  for (unsigned i = 0; i < 4; ++i) {
    p[i] = (uint8_t)n;
    n >>= 8;
  }
}

static uint32_t crc32(uint32_t crc, const uint8_t *p, size_t n) {
  crc = ~crc;
  while (n--) {
    crc ^= *p++;
    for (unsigned i = 0; i < 8; ++i) {
      crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
    }
  }
  return ~crc;
}

typedef struct {
  const uint8_t *p, *end;
} pb_t;

static bool varint(pb_t *b, uint32_t *out) {
  uint32_t v = 0;
  for (unsigned shift = 0; shift < 35 && b->p < b->end; shift += 7) {
    uint8_t c = *b->p++;
    if (shift == 28 && c > 15) {
      return false;
    }
    v |= (uint32_t)(c & 127u) << shift;
    if (!(c & 128u)) {
      *out = v;
      return true;
    }
  }
  return false;
}

static bool bytes(pb_t *b, pb_t *child) {
  uint32_t n;
  if (!varint(b, &n) || n > (size_t)(b->end - b->p)) {
    return false;
  }
  child->p   = b->p;
  child->end = b->p += n;
  return true;
}

static bool hash(pb_t b, uint8_t digest[32]) {
  uint32_t key, type;
  pb_t     value;
  // Strict canonical metadata is deliberate: reject unsupported algorithms,
  // duplicate fields and ambiguous protobuf encodings before touching flash.
  if (!varint(&b, &key) || key != 8 || !varint(&b, &type) || type != 3 || !varint(&b, &key) || key != 18 ||
      !bytes(&b, &value) || b.p != b.end || value.end - value.p != 32) {
    return false;
  }
  for (unsigned i = 0; i < 32; ++i) {
    digest[i] = value.p[31 - i];
  }
  return true;
}

bool secure_dfu_parse_command(const uint8_t *data, size_t len, uint32_t max_image, uint16_t fwid,
                              secure_dfu_image_t *image) {
  if (!data || !image || len == 0 || len > SECURE_DFU_COMMAND_MAX) {
    return false;
  }
  pb_t     packet = {data, data + len}, command, init;
  uint32_t key, value, seen = 0;
  // Packet.command -> Command{op_code:INIT, init:InitCommand}. SignedCommand
  // is explicitly rejected, never accepted without verifying its signature.
  if (!varint(&packet, &key) || key != 10 || !bytes(&packet, &command) || packet.p != packet.end ||
      !varint(&command, &key) || key != 8 || !varint(&command, &value) || value != 1 || !varint(&command, &key) ||
      key != 18 || !bytes(&command, &init) || command.p != command.end) {
    return false;
  }
  secure_dfu_image_t candidate = {0};
  bool               sd_match  = false;
  while (init.p != init.end) {
    if (!varint(&init, &key) || key == 0 || (key >> 3) > 9) {
      return false;
    }
    uint32_t field = key >> 3, wire = key & 7u;
    if ((seen & (1u << field)) && field != 3) {
      return false;
    }
    seen |= 1u << field;
    if (field == 8 && wire == 2) {
      pb_t h;
      if (!bytes(&init, &h) || !hash(h, candidate.sha256)) {
        return false;
      }
    } else if (field == 3 && wire == 2) {
      pb_t req;
      if (!bytes(&init, &req) || req.p == req.end) {
        return false;
      }
      while (req.p != req.end) {
        if (!varint(&req, &value) || value > UINT16_MAX) {
          return false;
        }
        sd_match |= value == fwid;
      }
    } else {
      if (wire != 0 || !varint(&init, &value)) {
        return false;
      }
      switch (field) {
        case 1:
          break; // No anti-rollback claim in this unsigned lab profile.
        case 2:
          if (value != SECURE_DFU_HW_VERSION) {
            return false;
          }
          break;
        case 3:
          if (value > UINT16_MAX) {
            return false;
          }
          sd_match |= value == fwid;
          break;
        case 4:
        case 5:
        case 6:
        case 9:
          if (value != 0) {
            return false;
          }
          break;
        case 7:
          candidate.size = value;
          break;
        default:
          return false;
      }
    }
  }
  if ((seen & 0x18Cu) != 0x18Cu || !sd_match || candidate.size < 8 || candidate.size > max_image ||
      (candidate.size & 3u)) {
    return false;
  }
  *image = candidate;
  return true;
}

void secure_dfu_init(secure_dfu_t *s) {
  memset(s, 0, sizeof(*s));
}

static size_t checksum(secure_dfu_t *s, uint8_t *out) {
  put32(out, s->selected == COMMAND ? s->command_offset : s->committed + s->object_offset);
  put32(out + 4, s->selected == COMMAND ? s->command_crc : s->data_crc);
  return 8;
}

static uint8_t create(secure_dfu_t *s, uint8_t type, uint32_t n) {
  // A flash error/timeout may still own a pointer into the object buffer.
  // Do not reuse that storage for a new transfer before a hardware reset.
  if (s->failed || s->completed) {
    return NOT_PERMITTED;
  }
  if (type == COMMAND) {
    if (n == 0 || n > SECURE_DFU_COMMAND_MAX) {
      return BAD_PARAMETER;
    }
    uint16_t prn = s->prn;
    secure_dfu_init(s);
    s->prn          = prn;
    s->command_size = n;
  } else if (type == DATA) {
    if (!s->initialized || s->failed || s->completed) {
      return NOT_PERMITTED;
    }
    uint32_t left = s->image.size - s->committed;
    if (n == 0 || n != (left < SECURE_DFU_OBJECT_MAX ? left : SECURE_DFU_OBJECT_MAX)) {
      return BAD_PARAMETER;
    }
    // CREATE rolls back only the unexecuted RAM object, never committed flash.
    s->object_size   = n;
    s->object_offset = 0;
    s->data_crc      = s->committed_crc;
    s->executed      = false;
  } else {
    return BAD_TYPE;
  }
  s->selected  = type;
  s->prn_count = 0;
  return OK;
}

static uint8_t execute(secure_dfu_t *s) {
  if (s->failed) {
    return FAILED;
  }
  if (s->selected == COMMAND) {
    if (s->initialized) {
      return OK; // Resume re-executes an identical command.
    }
    if (!s->command_size || s->command_offset != s->command_size ||
        !secure_dfu_parse_command(s->command, s->command_size, secure_dfu_max_image(), secure_dfu_fwid(), &s->image)) {
      return BAD_OBJECT;
    }
    if (!secure_dfu_begin(&s->image)) {
      s->failed = true;
      return FAILED;
    }
    s->initialized = true;
    return OK;
  }
  if (s->selected != DATA || !s->initialized) {
    return NOT_PERMITTED;
  }
  if (s->executed) {
    return OK;
  }
  if (!s->object_size || s->object_offset != s->object_size) {
    return NOT_PERMITTED;
  }
  if (!secure_dfu_write(s->data, s->object_size)) {
    s->failed = true;
    return FAILED;
  }
  s->committed += s->object_size;
  s->committed_crc = s->data_crc;
  s->object_offset = 0;
  s->object_size   = 0;
  s->executed      = true;
  if (s->committed == s->image.size) {
    if (!secure_dfu_finish()) {
      s->failed = true;
      return BAD_OBJECT;
    }
    s->completed = true;
  }
  return OK;
}

size_t secure_dfu_control(secure_dfu_t *s, const uint8_t *in, size_t len, uint8_t out[15]) {
  if (!in || !len) {
    return 0;
  }
  uint8_t op = in[0], status = BAD_PARAMETER;
  size_t  extra = 0;
  switch (op) {
    case CREATE:
      if (len == 6) {
        status = create(s, in[1], get32(in + 2));
      }
      break;
    case SET_PRN:
      if (len == 3) {
        s->prn       = (uint16_t)in[1] | (uint16_t)in[2] << 8;
        s->prn_count = 0;
        status       = OK;
      }
      break;
    case CHECKSUM:
      if (len == 1) {
        status = s->failed ? FAILED : s->selected ? OK : NOT_PERMITTED;
        if (status == OK) {
          extra = checksum(s, out + 3);
        }
      }
      break;
    case SELECT:
      if (len == 2) {
        status = in[1] == COMMAND || in[1] == DATA ? OK : BAD_TYPE;
        if (status == OK) {
          s->selected = in[1];
          put32(out + 3, s->selected == COMMAND ? SECURE_DFU_COMMAND_MAX : SECURE_DFU_OBJECT_MAX);
          extra = 4 + checksum(s, out + 7);
        }
      }
      break;
    case EXECUTE:
      if (len == 1) {
        status = execute(s);
      }
      break;
    default:
      status = NOT_SUPPORTED;
      break;
  }
  out[0] = 0x60;
  out[1] = op;
  out[2] = status;
  if (status == OK) {
    secure_dfu_activity();
  }
  return 3 + extra;
}

size_t secure_dfu_packet(secure_dfu_t *s, const uint8_t *in, size_t len, uint8_t out[15]) {
  bool     command = s->selected == COMMAND;
  uint32_t offset  = command ? s->command_offset : s->object_offset;
  uint32_t size    = command ? s->command_size : s->object_size;
  if (s->failed || !in || !len || !s->selected || offset > size || len > size - offset ||
      (command ? s->initialized : !s->initialized || s->executed)) {
    // Rejection has not copied bytes or started flash work. Preserve the
    // object/CRC so a valid retry or CREATE can recover. Platform flash or
    // validation failures stay latched until reset; never clear that latch here.
    out[0] = 0x60;
    out[1] = 8;
    out[2] = NOT_PERMITTED;
    return 3;
  }
  memcpy((command ? s->command : (uint8_t *)s->data) + offset, in, len);
  if (command) {
    s->command_offset += len;
    s->command_crc = crc32(s->command_crc, in, len);
  } else {
    s->object_offset += len;
    s->data_crc = crc32(s->data_crc, in, len);
  }
  secure_dfu_activity();
  if (s->prn && ++s->prn_count >= s->prn) {
    s->prn_count = 0;
    out[0]       = 0x60;
    out[1]       = CHECKSUM;
    out[2]       = OK;
    return 3 + checksum(s, out + 3);
  }
  return 0;
}
