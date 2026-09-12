#ifndef APP_ERROR_H__
#define APP_ERROR_H__
#include <stdint.h>
void test_app_error(uint32_t error);
#define APP_ERROR_CHECK(error) \
  do {                         \
    uint32_t e = (error);      \
    if (e)                     \
      test_app_error(e);       \
  } while (0)
#endif
