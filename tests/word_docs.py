"""Tiny synthetic WordDocument builders for tests."""
from __future__ import annotations

import struct

from cfb import build_cfb


def make_fib(
    ccp_text: int,
    fc_clx: int = 0,
    lcb_clx: int = 0,
    f_complex: bool = True,
    fc_min: int = 0,
    fc_mac: int = 0,
) -> bytes:
    b = bytearray(512)
    struct.pack_into("<HH", b, 0, 0xA5EC, 0x00C1)  # wIdent, nFib
    flags = 1 << 9  # fWhichTblStm -> 1Table
    if f_complex:
        flags |= 1 << 2
    struct.pack_into("<H", b, 0x0A, flags)
    struct.pack_into("<II", b, 0x18, fc_min, fc_mac)
    struct.pack_into("<H", b, 32, 14)  # csw
    struct.pack_into("<H", b, 62, 22)  # cslw after FibRgW97
    struct.pack_into("<I", b, 76, ccp_text)  # ccpText at FibRgLw97 + 12
    struct.pack_into("<H", b, 152, 34)  # cbRgFcLcb
    struct.pack_into("<iI", b, 418, fc_clx, lcb_clx)  # pair 33: fcClx/lcbClx
    return bytes(b)


def make_simple_doc_bytes(text: str) -> bytes:
    encoded = text.encode("cp1252")
    text_off = 512
    wd = bytearray(
        make_fib(
            ccp_text=len(text),
            fc_clx=0,
            lcb_clx=0,
            f_complex=False,
            fc_min=text_off,
            fc_mac=text_off + len(encoded),
        )
    )
    wd[text_off : text_off + len(encoded)] = encoded
    return build_cfb({"WordDocument": bytes(wd)})
