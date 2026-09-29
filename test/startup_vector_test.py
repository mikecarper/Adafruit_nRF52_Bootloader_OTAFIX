#!/usr/bin/env python3
"""Link the compact startup and check every real vector against Nordic's table."""

from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "lib/nrfx/mdk"


class StartupVectors(unittest.TestCase):
    def test_linked_vectors_and_strong_handlers(self):
        gcc = shutil.which("arm-none-eabi-gcc")
        if not gcc:
            self.skipTest("Arm toolchain unavailable")
        prefix = gcc.removesuffix("gcc")
        header = (SDK / "nrf52840.h").read_text()
        last_irq = max(int(n) for n in re.findall(r"\w+_IRQn\s*=\s*(-?\d+)", header))
        original = (SDK / "gcc_startup_nrf52840.S").read_text()
        entries = re.findall(r"^\s*\.long\s+(\w+)", original, re.M)[:16 + last_irq + 1]
        self.assertEqual(last_irq, 47)
        self.assertEqual(len(entries), 64)
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            linker = work / "test.ld"
            linker.write_text("""
ENTRY(Reset_Handler)
MEMORY { FLASH (rx) : ORIGIN = 0xF4000, LENGTH = 0xA000
         RAM (rwx) : ORIGIN = 0x20008000, LENGTH = 0x28000 }
SECTIONS {
 .text : { KEEP(*(.isr_vector)) *(.text*) } > FLASH
 __etext = .;
 .data : AT(__etext) { __data_start__ = .; *(.data*) } > RAM
 .bss (NOLOAD) : { __bss_start__ = .; *(.bss*) __bss_end__ = .; } > RAM
 .stack (NOLOAD) : { *(.stack) } > RAM
}
""", encoding="ascii")
            stubs = work / "stubs.S"
            # Strong interrupt definitions must override the vendor weak
            # aliases, even though the compact table lives in a wrapper.
            strong = ["SystemInit", "main", "USBD_IRQHandler", "POWER_CLOCK_IRQHandler",
                      "SWI0_EGU0_IRQHandler", "RTC1_IRQHandler", "SysTick_Handler"]
            stubs.write_text(".syntax unified\n.thumb\n.text\n" + "".join(
                f".global {name}\n.type {name}, %function\n.thumb_func\n{name}:\n bx lr\n"
                for name in strong), encoding="ascii")
            elf = work / "startup.elf"
            subprocess.run([gcc, "-mthumb", "-mcpu=cortex-m4", "-nostdlib",
                            "-D__START=main", "-D__STARTUP_CLEAR_BSS", "-D__HEAP_SIZE=0",
                            "-Wl,--gc-sections", "-T", str(linker),
                            str(ROOT / "src/startup_nrf52840.S"), str(stubs),
                            "-o", str(elf)], check=True, capture_output=True)
            symbols = subprocess.check_output([prefix + "nm", "-S", str(elf)], text=True)
            addresses = {parts[-1]: int(parts[0], 16) for line in symbols.splitlines()
                         if len(parts := line.split()) >= 3}
            self.assertEqual(addresses["__isr_vector"], 0xF4000)
            self.assertNotIn("__otafix_unused_sdk_vectors", addresses)
            self.assertRegex(symbols, r"000f4000 00000100 .* __isr_vector")
            for name in strong[2:]:
                self.assertNotEqual(addresses[name], addresses["Default_Handler"])
            binary = work / "text.bin"
            subprocess.run([prefix + "objcopy", "--dump-section", f".text={binary}",
                            str(elf)], check=True, capture_output=True)
            vectors = struct.unpack_from("<64I", binary.read_bytes())
            for index, name in enumerate(entries):
                expected = 0 if name == "0" else addresses[name] | (0 if index == 0 else 1)
                self.assertEqual(vectors[index], expected, (index, name))


if __name__ == "__main__":
    unittest.main()
