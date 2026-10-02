#!/usr/bin/env python3
"""Link each nRF52 vector table and execute the stackless B1 fault recovery."""

import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "lib/nrfx/mdk"

try:
    import unicorn
    from unicorn import arm_const
except ImportError:
    unicorn = None


class DfuHardFaultTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gcc = shutil.which("arm-none-eabi-gcc")
        if not cls.gcc:
            if os.environ.get("OTAFIX_REQUIRE_DFU_EMULATOR") == "1":
                raise AssertionError("Arm compiler is required for the HardFault recovery regression")
            raise unittest.SkipTest("Arm compiler unavailable")
        cls.prefix = cls.gcc.removesuffix("gcc")
        cls.directory = tempfile.TemporaryDirectory(prefix="otafix-dfu-hardfault-")
        cls.work = Path(cls.directory.name)
        linker = cls.work / "test.ld"
        linker.write_text('''
ENTRY(Reset_Handler)
MEMORY { FLASH (rx) : ORIGIN = 0xF4000, LENGTH = 0xA000
         RAM (rwx) : ORIGIN = 0x20008000, LENGTH = 0x18000 }
SECTIONS {
 .text : { KEEP(*(.isr_vector)) *(.text*) } > FLASH
 __etext = .;
 .data : AT(__etext) { __data_start__ = .; *(.data*) } > RAM
 .bss (NOLOAD) : { __bss_start__ = .; *(.bss*) __bss_end__ = .; } > RAM
 .stack (NOLOAD) : { *(.stack) } > RAM
}
''', encoding="ascii")
        stubs = cls.work / "stubs.S"
        stubs.write_text('''.syntax unified
.thumb
.text
.global main
.type main, %function
.thumb_func
main: b .
''', encoding="ascii")
        cls.images = {}
        for variant, macro in (("nrf52", "NRF52832_XXAA"),
                               ("nrf52833", "NRF52833_XXAA"),
                               ("nrf52840", "NRF52840_XXAA")):
            elf = cls.work / (variant + ".elf")
            startup = (ROOT / "src/startup_nrf52840.S" if variant == "nrf52840"
                       else SDK / ("gcc_startup_" + variant + ".S"))
            subprocess.run([
                cls.gcc, "-mcpu=cortex-m4", "-mthumb", "-Oz", "-nostdlib",
                "-ffunction-sections", "-fdata-sections", "-D" + macro,
                "-D__START=main", "-D__STARTUP_CLEAR_BSS", "-D__HEAP_SIZE=0",
                "-DCONFIG_GPIO_AS_PINRESET", "-DCONFIG_NFCT_PINS_AS_GPIOS",
                "-I" + str(SDK), "-I" + str(ROOT / "src/cmsis/include"),
                "-Wl,--gc-sections,--undefined=otafix_system_reset", "-T", str(linker),
                str(startup), str(ROOT / "src/dfu_hardfault.c"),
                str(ROOT / "src/system_nrf52.c"), str(stubs),
                "-o", str(elf),
            ], check=True, capture_output=True, text=True)
            output = subprocess.check_output([cls.prefix + "nm", "-S", str(elf)], text=True)
            symbols = {parts[-1]: int(parts[0], 16) for line in output.splitlines()
                       if len(parts := line.split()) >= 3}
            binary = cls.work / (variant + ".bin")
            subprocess.run([cls.prefix + "objcopy", "-Obinary", str(elf), str(binary)],
                           check=True, capture_output=True)
            cls.images[variant] = (elf, symbols, binary.read_bytes())

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_all_three_vectors_use_stackless_strong_handler(self):
        for variant, (elf, symbols, binary) in self.images.items():
            with self.subTest(variant=variant):
                self.assertEqual(struct.unpack_from("<I", binary, 12)[0],
                                 symbols["HardFault_Handler"] | 1)
                assembly = subprocess.check_output([
                    self.prefix + "objdump", "-d", "--disassemble=HardFault_Handler", str(elf)
                ], text=True)
                self.assertNotRegex(assembly, r"\b(push|pop|bl|blx|sp)\b")
                self.assertRegex(assembly, r"\bldr\s+r0,\s*\[r1")
                self.assertRegex(assembly, r"\bstr\s+r0,\s*\[r1")
                self.assertRegex(assembly, r"\bb\.n\s+[0-9a-f]+\s+<otafix_system_reset>")
                self.assertLess(abs(symbols["otafix_system_reset"] - symbols["HardFault_Handler"]), 2048)
                reset = subprocess.check_output([
                    self.prefix + "objdump", "-d", "--disassemble=otafix_system_reset", str(elf)
                ], text=True)
                self.assertNotRegex(reset, r"\b(push|pop|bl|blx|sp)\b")
                self.assertEqual(len(re.findall(r"\bdsb\b", reset)), 2)
                self.assertFalse(any("NVIC_SystemReset" in name for name in symbols))
                system_init = subprocess.check_output([
                    self.prefix + "objdump", "-d", "--disassemble=SystemInit", str(elf)
                ], text=True)
                self.assertIn("<otafix_system_reset>", system_init)

    def emulate(self, variant, magic, ordinary=False, priority_group=0):
        if unicorn is None:
            if os.environ.get("OTAFIX_REQUIRE_DFU_EMULATOR") == "1":
                self.fail("Unicorn is required for the HardFault recovery regression")
            self.skipTest("Unicorn unavailable")
        _, symbols, binary = self.images[variant]
        machine = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB | unicorn.UC_MODE_MCLASS)
        machine.mem_map(0xF4000, 0xA000)
        ram_size = 0x40000 if variant == "nrf52840" else 0x20000
        machine.mem_map(0x20000000, ram_size)
        machine.mem_map(0x40000000, 0x1000)
        machine.mem_map(0xE000E000, 0x1000)
        machine.mem_write(0xF4000, binary)
        machine.mem_write(0x4000051C, struct.pack("<II", magic, 0x53))
        machine.mem_write(0xE000ED0C, struct.pack("<I", 0xFA050000 | priority_group))
        peer = bytes(range(62))
        machine.mem_write(0x20007F80, peer)
        # Leave MSP beyond real SRAM for HardFault; no mapped stack can hide
        # an accidental C prologue, C call or exception-frame dereference.
        bad_stack = 0x20000000 + ram_size + 104
        machine.reg_write(arm_const.UC_ARM_REG_MSP,
                          0x20000000 + ram_size if ordinary else bad_stack)
        machine.reg_write(arm_const.UC_ARM_REG_CONTROL, 0)
        writes = []
        def record_write(uc, access, address, size, value, context):
            writes.append((address, size, value))
            if address == 0xE000ED0C:
                uc.emu_stop()
        machine.hook_add(unicorn.UC_HOOK_MEM_WRITE, record_write)
        entry = symbols["otafix_system_reset" if ordinary else "HardFault_Handler"]
        machine.emu_start(entry | 1, 0, count=100)
        self.assertEqual(bytes(machine.mem_read(0x20007F80, 62)), peer)
        self.assertEqual(struct.unpack("<I", machine.mem_read(0x40000520, 4))[0], 0x53)
        if not ordinary:
            self.assertEqual(machine.reg_read(arm_const.UC_ARM_REG_MSP), bad_stack)
        return machine, writes

    def test_b1_fault_resets_with_a8_and_retained_peer_even_with_invalid_msp(self):
        for variant in self.images:
            with self.subTest(variant=variant):
                machine, writes = self.emulate(variant, 0xB1)
                self.assertEqual(writes, [(0x4000051C, 4, 0xA8), (0xE000ED0C, 4, 0x05FA0004)])
                self.assertEqual(struct.unpack("<I", machine.mem_read(0x4000051C, 4))[0], 0xA8)

    def test_other_faults_halt_without_touching_retained_state_or_requesting_reset(self):
        for variant in self.images:
            for magic in (0, 0xA8, 0x57, 0x6A, 0x6B, 0xFF):
                with self.subTest(variant=variant, magic=magic):
                    machine, writes = self.emulate(variant, magic)
                    self.assertEqual(writes, [])
                    self.assertEqual(struct.unpack("<I", machine.mem_read(0x4000051C, 4))[0], magic)

    def test_shared_normal_reset_preserves_priority_group(self):
        for variant in self.images:
            for group in (0, 0x300, 0x700):
                with self.subTest(variant=variant, group=group):
                    _, writes = self.emulate(variant, 0x57, ordinary=True, priority_group=group)
                    self.assertEqual(writes, [(0xE000ED0C, 4, 0x05FA0004 | group)])


if __name__ == "__main__":
    unittest.main()
