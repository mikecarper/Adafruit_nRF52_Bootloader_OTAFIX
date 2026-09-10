# Mercer USB investigation - 10 September 2026

Two different failure layers were found. The RAK3401 has a directly observed
application-side USB wait hang. The Pi also lost its hub tree unattended;
the electrical or controller-level cause of that event is not yet established.
Neither observation is a successful 2.4.7 hardware qualification.

## Pi-side evidence

All times below are Pacific daylight time. The owner confirmed that the hub
resets at about 01:19-01:21 happened unattended, and that two of the three hubs
have external power supplies. Which physical hub is bus-powered has not yet
been confirmed; USB descriptors report all three as self-powered and therefore
cannot resolve the discrepancy with the actual wiring.

The Pi is a Zero 2 W running `6.12.34+rpt-rpi-v8`, with root storage on SD.
`dwc_otg.speed=1` is already present. Every external hub/device was at full
speed, 12 Mb/s; the virtual root-hub line's 480 Mb/s label is not the speed
of the attached devices.

```text
Pi USB controller (dwc_otg)
`-- 1-1: Terminus four-port hub
    |-- RAK3401
    |-- 1-1.2: Realtek hub
    |   |-- T1000-E
    |   |-- MeshTower V2 SD
    |   |-- T096 (two CDC interfaces)
    |   `-- XIAO nRF52840
    |-- 1-1.3: Terminus four-port hub
    |   |-- RAK4631
    |   |-- Mesh Pocket
    |   |-- Heltec V4 (ESP32)
    |   `-- secondary USB Ethernet, link down
    `-- primary USB Ethernet, default network route
```

| Time | Kernel observation |
| --- | --- |
| 01:19:31 | Root port reports `disabled by hub (EMI?), re-enabling...`; upstream hub and its attached devices disconnect. |
| 01:19:31 | `dwc_otg_hcd_urb_dequeue` times out waiting for an FSM non-periodic transfer during teardown. |
| 01:19:32 onward | Hub tree begins re-enumerating. |
| 01:19:40 | Downstream Terminus hub has a descriptor-read error, `-71`, then enumerates. |
| 01:21:06-01:21:31 | Realtek hub and its four nRF52 children disappear and return. |
| 01:26:26-01:26:28 | Primary USB Ethernet loses and regains carrier. |

These events predate this test session's first hardware access. There were no
new kernel USB errors during the subsequent serial and SWD diagnostics up to
the 02:09 checkpoint. This is a short observation window, not a stress pass.

The Pi's throttling mask was zero. That does not measure voltage at each hub
or rule out a peripheral power problem. All three hubs were active and reported
zero runtime-suspended time since their last enumeration, making autosuspend
an unlikely explanation for the observed current state. Missing earlier
records prevent that observation from ruling out every historical event.

The kernel's "EMI?" text is a recovery message for an unexpectedly disabled
port, not a measurement proving radio interference. The transfer timeout is
in the cancellation path and followed the disconnect; it cannot, by itself,
establish the initial cause. See the [Pi hub recovery code](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/drivers/usb/core/hub.c)
and [DWC transfer cancellation code](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/drivers/usb/host/dwc_otg/dwc_otg_hcd.c).

Error `-71` is `EPROTO`: it can represent a protocol error, missing response,
or another bus fault. Cables, hubs, attached-device behavior and the controller
remain candidates. See [Linux USB error definitions](https://docs.kernel.org/driver-api/usb/error-codes.html).

Because the preferred Ethernet route shares the failing USB tree, loss of
remote access need not mean that the Pi CPU crashed. The available logs do not
prove the cause of the earlier reported whole-Pi freezes. No panic or OOM was
found in the available captures; older journal coverage is incomplete and
`pstore` is empty.

## RAK3401: directly observed firmware hang

The recorded SWD wiring was recovered from the original lab instructions:

| Signal | Physical Pi pin | BCM GPIO |
| --- | ---: | ---: |
| SWCLK | 23 | 11 |
| SWDIO | 24 | 8 |
| Reset | 18 | 24 |
| Ground | 20 | - |

The Pi's power pins are not connected to the target. The installed OpenOCD
`raspberrypi-native.cfg` matches the clock/data mapping. Reset was not driven.
The chip's FICR identity was checked against the existing board backup before
capture. Two complete 1 MiB flash reads matched byte-for-byte; UICR and RAM
were also captured privately. The CPU was resumed after every halt. No flash,
UICR, application settings or radio settings were written.

The current application contains the version string
`v1.17.1.6-halo-keymind-cascade-dev-f778d14c`. The installed bootloader is the
older lab candidate `0x02040405`, manifest CRC `0x9290C72A`, not 2.4.7.

The RAK3401 returned no data through either text CLI or the framed Companion
protocol, even with ModemManager and the serial bridge paused. SWD captured:

| Value | Observation |
| --- | --- |
| Program counter | `0x0002B316`, unchanged at the later 02:04:28 capture |
| Link register | `0x000753C3` |
| R4 | `0x40027000`, the USBD peripheral base |
| xPSR | `0x41000000`, thread mode |
| USBD EVENTCAUSE | `0x00000000`, READY bit cleared |
| USBD ENABLE / USBPULLUP | `1 / 1` |
| POWER USBREGSTATUS | `3`, VBUS detected and USB supply ready |
| CFSR / HFSR | `0 / 0`, no recorded configurable/hard fault |

Disassembling the actual flash readback shows a tight loop at
`0x0002B312..0x0002B318` reading `USBD.EVENTCAUSE` and waiting for bit 11.
The caller's instructions match the USB post-SoftDevice-enable path. This
does not depend on guessing addresses from a different application ELF.

The same unbounded wait is present in the installed Adafruit TinyUSB source,
and in this bootloader's pinned TinyUSB copy at
`lib/tinyusb/src/portable/nordic/nrf5x/dcd_nrf5x.c`, in
`tusb_hal_nrf_power_event()` under `USB_EVT_READY`. READY is a write-one-to-clear
event. Re-entering that path after another handler has consumed READY can wait
forever unless the early guard recognizes the already-completed state.

Duplicate/re-entrant READY handling around the SoftDevice clock-ownership
transition is the leading explanation. The exact event ordering has not yet
been captured. The live wait hang is proven; that particular ordering is an
inference. The existing bootloader's later HFCLK request does not protect the
earlier READY wait.

This explains the RAK3401's silent USB application. The XIAO was also silent,
but it has no SWD connection and the same cause has not been established there.
It also does not prove that this application hang caused the Pi's hub resets.

## Actions taken and remaining work

- Built and packaged 2.4.7-preview.1 without changing firmware logic.
- Queried boards serially, one at a time. Paused ModemManager and `mctomqtt`
  only around serial probes, then restored both; the latter continues its
  pre-existing restart loop because its RAK3401 has no serial response.
- Captured the RAK3401 state and fresh backups over the verified SWD wiring.
- Did not reset hubs, unbind USB drivers, reboot the Pi, change boot options,
  power-cycle targets, flash firmware, or clear bonds/messages/settings.
- Held physical update qualification pending a USB READY fix and a healthy
  baseline. Fixing MeshCore as well as the bootloader requires both projects;
  a bootloader-only update cannot replace the USB driver in an existing app.
- For the host fault, verify the first hub's actual power supply and upstream
  OTG cable, then isolate downstream branches under controlled conditions.
  Pi power guidance recommends a [powered hub for Zero peripherals](https://www.raspberrypi.com/documentation/computers/getting-started.html#raspberry-pi-zero-usb-devices).
  Driver or kernel A/B tests are a separate controlled change, not a confirmed
  fix. Do not issue a whole-hub reset over the only working network path.

Private raw logs, flash/UICR/RAM backups, disassembly inputs and probe scripts
are under `/home/mesh/otafix-247-test.KS9Dp5/` on the VM and
`/home/mikec/hwtest/otafix-247.kOqqF1/` on the Pi. Backups can contain node keys;
they are excluded from the test ZIP and from Git.
