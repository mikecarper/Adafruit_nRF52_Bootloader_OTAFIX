#!/usr/bin/env python3
"""Exercise production application-handoff write protection against host registers."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "lib/sdk11/components/libraries/bootloader_dfu/bootloader_util.c"


def definition(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for position in range(opening, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[start:position + 1]
    raise AssertionError("unterminated production definition: " + signature)


class BootloaderWritePolicyTests(unittest.TestCase):
    def test_mbr_and_settings_protected_but_loader_and_params_writable(self):
        source = SOURCE.read_text()
        production = "\n".join(definition(source, signature) for signature in (
            "static uint32_t bootloader_util_flash_protect(",
            "void bootloader_util_app_start(",
        ))
        common = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#define NRF_SUCCESS 0u
#define NRF_ERROR_INVALID_PARAM 7u
#define NRF_ERROR_NO_MEM 4u
#define CODE_PAGE_SIZE 4096u
#define MBR_SIZE 4096u
static uint32_t application;
static void bootloader_util_reset(uint32_t address) { application = address; }
'''
        acl = r'''
#define ACL_PRESENT 1
#define ACL_REGIONS_COUNT 8
#define ACL_ACL_PERM_WRITE_Disable 1u
#define ACL_ACL_PERM_WRITE_Pos 1u
#define BOOTLOADER_REGION_START 0xF4000u
#define BOOTLOADER_SETTINGS_ADDRESS 0xFF000u
typedef struct { uint32_t ADDR, SIZE, PERM; } ACL_ACL_Type;
static struct { ACL_ACL_Type ACL[8]; } registers;
#define NRF_ACL (&registers)
static bool protected(uint32_t address) {
  for (unsigned i = 0; i < 8; ++i) {
    const ACL_ACL_Type *region = &registers.ACL[i];
    if ((region->PERM & 2u) && address >= region->ADDR &&
        address < region->ADDR + region->SIZE) return true;
  }
  return false;
}
'''
        bprot = r'''
#define BPROT_PRESENT 1
#define BPROT_REGIONS_NUM 128
#define BOOTLOADER_REGION_START 0x78000u
#define BOOTLOADER_SETTINGS_ADDRESS 0x7F000u
static struct { uint32_t CONFIG0, CONFIG1, CONFIG2, CONFIG3; } registers;
#define NRF_BPROT (&registers)
static bool protected(uint32_t address) {
  const uint32_t page = address / CODE_PAGE_SIZE;
  const uint32_t bits[] = { registers.CONFIG0, registers.CONFIG1,
                            registers.CONFIG2, registers.CONFIG3 };
  return (bits[page / 32u] & (1u << (page % 32u))) != 0;
}
'''
        checks = r'''
int main(void) {
  bootloader_util_app_start(0x26000u);
  assert(application == 0x26000u);
  assert(protected(0));
  assert(protected(MBR_SIZE - 1));
  assert(!protected(MBR_SIZE));
  for (uint32_t address = BOOTLOADER_REGION_START;
       address < BOOTLOADER_SETTINGS_ADDRESS; address += CODE_PAGE_SIZE) {
    assert(!protected(address));
    assert(!protected(address + CODE_PAGE_SIZE - 1));
  }
  assert(protected(BOOTLOADER_SETTINGS_ADDRESS));
  assert(protected(BOOTLOADER_SETTINGS_ADDRESS + CODE_PAGE_SIZE - 1));
}
'''
        with tempfile.TemporaryDirectory(prefix="bootloader-write-policy-") as directory:
            for name, registers in (("acl", acl), ("bprot", bprot)):
                with self.subTest(backend=name):
                    binary = Path(directory) / (name + (".exe" if os.name == "nt" else ""))
                    subprocess.run([
                        os.environ.get("CC", "gcc"), "-std=c11", "-O2", "-Wall", "-Wextra",
                        "-Werror", "-x", "c", "-", "-o", str(binary),
                    ], input=common + registers + production + checks, text=True, check=True)
                    subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
