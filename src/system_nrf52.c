#include "nrf.h"
#include "system_reset.h"

// Keep the vendor startup errata logic while sharing its reset implementation
// with the rest of the bootloader. Include nrf.h before redirecting the name so
// the CMSIS inline definition itself remains untouched.
#define NVIC_SystemReset otafix_system_reset

#if defined(NRF52840_XXAA)
  #include "../lib/nrfx/mdk/system_nrf52840.c"
#elif defined(NRF52833_XXAA)
  #include "../lib/nrfx/mdk/system_nrf52833.c"
#elif defined(NRF52) || defined(NRF52832_XXAA)
  #include "../lib/nrfx/mdk/system_nrf52.c"
#else
  #error Unsupported Nordic SystemInit variant
#endif
