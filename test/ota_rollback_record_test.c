#include <assert.h>
#include "ota_rollback_record.h"

int main(void) {
  static const uint32_t base = 0x26000;
  static const uint32_t page = MOTA_ROLLBACK_LEGACY_PAGE;
  mota_rollback_record_t record = {
      .magic = MOTA_ROLLBACK_MAGIC,
      .media = 0x51,
      .offset = 0x81000,
      .previous_size = 626000,
      .next_size = 627000,
      .phase = MOTA_ROLLBACK_READY,
  };
  record.crc32 = mota_rollback_crc(&record);
  const uint32_t phases[] = {
      MOTA_ROLLBACK_READY, MOTA_ROLLBACK_INSTALLING, MOTA_ROLLBACK_TRIAL,
      MOTA_ROLLBACK_RUNNING, MOTA_ROLLBACK_DONE,
  };
  for (size_t i = 0; i < sizeof(phases) / sizeof(phases[0]); ++i) {
    assert((record.phase & phases[i]) == phases[i]);
    record.phase = phases[i];
    assert(mota_rollback_valid(&record, base, page));
    assert(!!mota_rollback_should_restore(record.phase) == (i == 1 || i == 3));
  }
  assert(!mota_rollback_should_restore(MOTA_ROLLBACK_FAILED));
  assert(!mota_rollback_should_restore(0u));
  assert(!mota_rollback_should_restore(0xFFFFFFFAu));
  ++record.offset;
  assert(!mota_rollback_valid(&record, base, page));
  record.crc32 = mota_rollback_crc(&record);
  assert(mota_rollback_valid(&record, base, page));
  record.next_size = page - base + 1u;
  record.crc32 = mota_rollback_crc(&record);
  assert(!mota_rollback_valid(&record, base, page));
  return 0;
}
