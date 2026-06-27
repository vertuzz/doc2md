"""Tests for sprm decoding and paragraph/character property extraction."""
from __future__ import annotations

import struct

from doc2markdown.docreader import DocReader
from doc2markdown.formatting import Formatting, _toggle_on, decode_sprms
from doc2markdown.ole2 import OLE2Reader

from cfb import build_cfb


def test_decode_sprms_operand_sizes():
    g = struct.pack("<HB", 0x2416, 0x01) + struct.pack("<Hi", 0x6649, 1)
    m = decode_sprms(g)

    assert m[0x2416] == b"\x01"
    assert struct.unpack("<i", m[0x6649])[0] == 1


def test_decode_sprms_variable_length():
    g = struct.pack("<HBB", 0x646B, 2, 0xAA) + b"\xBB\xCC"
    m = decode_sprms(g)

    assert 0x646B in m
    assert m[0x646B] == b"\x02\xAA\xBB\xCC"


def test_decode_sprms_truncated_tail_is_safe():
    g = struct.pack("<HB", 0x2416, 0x01) + b"\x66"
    m = decode_sprms(g)

    assert m == {0x2416: b"\x01"}


def test_toggle_on_semantics():
    assert _toggle_on(0x01) is True
    assert _toggle_on(0x81) is True
    assert _toggle_on(0x00) is False
    assert _toggle_on(0x80) is False


def test_sprm_bit_fields():
    assert (0x2416 >> 10) & 7 == 1 and (0x2416 >> 13) & 7 == 1
    assert (0x6649 >> 10) & 7 == 1 and (0x6649 >> 13) & 7 == 3
    assert (0x0835 >> 10) & 7 == 2 and (0x0835 >> 13) & 7 == 0


def _make_fib(ccp_text, pairs):
    b = bytearray(512)
    struct.pack_into("<HH", b, 0, 0xA5EC, 0x00C1)
    struct.pack_into("<H", b, 0x0A, (1 << 9) | (1 << 2))
    struct.pack_into("<H", b, 32, 14)
    struct.pack_into("<H", b, 62, 22)
    struct.pack_into("<I", b, 76, ccp_text)
    max_idx = max(pairs) if pairs else 0
    struct.pack_into("<H", b, 152, max(34, max_idx + 1))
    for idx, (fc, lcb) in pairs.items():
        struct.pack_into("<iI", b, 154 + idx * 8, fc, lcb)
    return bytes(b)


def test_pap_and_chp_extraction_synthetic():
    ccp_text = 3
    text = b"AB\r"
    text_off = 512
    base = 2 * text_off
    fc_compressed = 0x40000000 | base

    clx = bytearray(b"\x02") + struct.pack("<i", 16)
    clx.extend(struct.pack("<II", 0, ccp_text))
    pcd = bytearray(8)
    struct.pack_into("<I", pcd, 2, fc_compressed)
    clx.extend(pcd)
    clx = bytes(clx)

    papx_bin = struct.pack("<II", 0, 2000) + struct.pack("<i", 2)
    chpx_bin = struct.pack("<II", 0, 2000) + struct.pack("<i", 3)
    table = clx + papx_bin + chpx_bin
    pairs = {
        33: (0, len(clx)),
        13: (len(clx), len(papx_bin)),
        12: (len(clx) + len(papx_bin), len(chpx_bin)),
    }

    wd = bytearray(_make_fib(ccp_text, pairs))
    wd[text_off : text_off + len(text)] = text
    wd.extend(b"\x00" * (1024 - len(wd)))

    pap = bytearray(512)
    struct.pack_into("<II", pap, 0, base, base + 2 * ccp_text)
    pap[8] = 50
    pap[511] = 1
    pap[100] = 9
    struct.pack_into("<H", pap, 101, 1)
    struct.pack_into("<HB", pap, 103, 0x2416, 0x01)
    struct.pack_into("<Hi", pap, 106, 0x6649, 1)
    struct.pack_into("<HB", pap, 112, 0x2640, 0x00)
    struct.pack_into("<HB", pap, 115, 0x2461, 0x00)
    wd[1024:1536] = pap

    chp_page = bytearray(512)
    struct.pack_into("<II", chp_page, 0, base, base + 2 * ccp_text)
    chp_page[8] = 50
    chp_page[511] = 1
    chp_page[50] = 6
    struct.pack_into("<HB", chp_page, 51, 0x0835, 0x01)
    struct.pack_into("<HB", chp_page, 54, 0x0836, 0x01)
    wd[1536:2048] = chp_page

    cfb = build_cfb({"WordDocument": bytes(wd), "1Table": table})
    doc = DocReader(OLE2Reader(cfb))
    fmt = Formatting(doc)

    pap = fmt.pap_for_cp(2)
    chp = fmt.chp_for_cp(0)

    assert doc.body == "AB\r"
    assert pap.f_in_table is True
    assert pap.itap == 1
    assert pap.outline_level == 0
    assert pap.istd == 1
    assert chp.bold is True
    assert chp.italic is True
    assert chp.underline is False
