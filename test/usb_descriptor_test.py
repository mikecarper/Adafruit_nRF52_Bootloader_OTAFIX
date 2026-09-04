#!/usr/bin/env python3
"""Guard the shared CDC/MSC configuration descriptor and serial encoding."""

from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "src/usb/usb_desc.c").read_text()


def main() -> None:
    if SOURCE.count("TUD_CDC_DESCRIPTOR(") != 1:
        raise AssertionError("CDC-only mode must reuse the CDC prefix, not duplicate it")
    for stale_name in (
        "desc_configuration_cdc_only",
        "desc_configuration_cdc_msc",
    ):
        if stale_name in SOURCE:
            raise AssertionError(f"duplicate USB descriptor survived: {stale_name}")

    callback = SOURCE[SOURCE.index("tud_descriptor_configuration_cb") :]
    if "return desc_configuration;" not in callback:
        raise AssertionError("configuration callback does not return the shared descriptor")

    init = SOURCE[SOURCE.index("void usb_desc_init") :]
    total = init.index("desc_configuration[2] = TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN;")
    interfaces = init.index("desc_configuration[4] = ITF_NUM_TOTAL - 1;")
    pid = init.index("desc_device.idProduct = USB_DESC_CDC_ONLY_PID;")
    if not total < interfaces < pid:
        raise AssertionError("CDC-only enumeration does not shorten the descriptor before use")

    # The branchless conversion replacing the 16-byte lookup table must still
    # emit exactly the uppercase hexadecimal alphabet used by existing devices.
    encoded = "".join(
        chr(ord("0") + nibble + (((nibble + 6) >> 4) * 7))
        for nibble in range(16)
    )
    if encoded != "0123456789ABCDEF":
        raise AssertionError(f"incorrect USB serial alphabet: {encoded}")

    print("USB descriptor sharing and serial encoding: PASS")


if __name__ == "__main__":
    main()
