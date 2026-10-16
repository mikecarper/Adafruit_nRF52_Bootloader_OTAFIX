# Mesh Solar internal-staging qualification candidate

This is a source/build candidate, **not a physically qualified download**.
`OTAFIX_BOARD_QUALIFICATION_PENDING` remains set, and both build systems require
test mode and an explicit packed test version. The header additionally requires
the qualification definition. Normal/recovery releases do not publish it.

## Confirmed subset used by the candidate

- The [manufacturer carrier pin map](https://resource.heltec.cn/download/MeshSolar/Pin_map/MeshSolar_pinmap.jpg)
  confirms the user button on **P1.10** and battery shutdown on **P1.03**.
  The candidate uses only the active-low user button, not a BSP alternative.
- Heltec contributor Quency-D's tested [watchdog change, PR 9337](https://github.com/meshtastic/firmware/pull/9337)
  establishes **P0.09 DONE / P0.10 WAKE**, previously unused on the earlier
  hardware, and a **1 ms high DONE pulse** followed by low. The existing common
  OTAFIX watchdog implementation already emits this exact pulse, feeds on entry,
  periodically during DFU, and before in-place flash work. This candidate uses
  a conservative 60-second feed interval and leaves WAKE as an input.
- The inspected HT-n5262 factory HEX CF2 preserves **239A:0071** and
  `HT-n5262`. This legacy shared manufacturer ID is retained, with a separate
  **`SOLARINT_DFU`** mOTA identity so another Heltec profile cannot self-update
  across the pin/layout boundary. It is not a newly allocated Adafruit ID.
- Current MeshCore Solar uses **S140 6.1.1**, application base **0x26000**.

## Deliberate exclusions

The conflicting BSP LED and QSPI definitions are not needed by this candidate.
It has **no LEDs, NeoPixel, QSPI, display or peripheral-rail outputs**. In
particular, it does not drive battery shutdown P1.03, display GPIO P0.12 or
BMS I2C P1.00/P1.01. It does not infer that flash is absent from the hardware.

The internal backend supports exact-base application deltas and signed
bootloader self-update within its workspace limits, but **not full application
mOTA images**. An ordinary flash-only application can use its existing SRAM
layout; optional hybrid staging requires an application that reserves and
authenticates the fixed 64 KiB retained arena.

## Qualification gates

Record the exact carrier revision, factory USB descriptors and `INFO_UF2.TXT`;
check the user button, cold USB/BLE entry, timeout and power/reset controller.
Measure the DONE waveform and verify that the hardware watchdog does not reset
the board during a long USB/BLE DFU, signed self-update or in-place delta apply.
Check the earlier revision and the watchdog revision separately, including
teardown/application handoff. The manufacturer's compatibility statement is
source evidence, not this project's physical qualification.

Use a matching internal-staging S140-v6 application for full failure-injection
and power-loss tests, including wrong-base/board rejection and preservation of
identity/settings. A future external-flash variant still needs the real storage
wiring and safe power/rail contract; do not alias a Tower, T1 or T114 image.
Complete the [ordinary hardware checks](meshcore-hardware-coverage.md#hardware-checks-before-promotion)
before removing the pending marker. This work has not flashed hardware.
