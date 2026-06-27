"""Tests for the doc reader: FIB parsing, piece-table decode and fallback."""
from __future__ import annotations

import struct

from doc2markdown.docreader import DocReader
from doc2markdown.ole2 import OLE2Reader

from cfb import build_cfb
from word_docs import make_fib


def make_clx(pieces):
    """Return CLX bytes for a Pcdt-only piece table."""
    cps = [pieces[0][0]] + [p[1] for p in pieces]
    plc = bytearray()
    for cp in cps:
        plc.extend(struct.pack("<I", cp))
    for _cp0, _cp1, fc, _compressed in pieces:
        pcd = bytearray(8)
        struct.pack_into("<I", pcd, 2, fc)
        plc.extend(pcd)
    clx = bytearray(b"\x02") + struct.pack("<i", len(plc)) + plc
    return bytes(clx)


def make_pcd_doc(pieces, ccp_text, extra=b""):
    clx = make_clx(pieces)
    wd = bytearray(make_fib(ccp_text, fc_clx=0, lcb_clx=len(clx)))
    wd.extend(extra)
    cfb = build_cfb({"WordDocument": bytes(wd), "1Table": clx})
    return DocReader(OLE2Reader(cfb))


def test_piece_table_utf16_and_compressed():
    utf16 = "Hello ".encode("utf-16le")
    comp = b"World"
    fib_size = 512
    u_wd = fib_size
    c_wd = fib_size + len(utf16)
    pieces = [
        (0, 6, u_wd, False),
        (6, 11, 0x40000000 | (2 * c_wd), True),
    ]

    doc = make_pcd_doc(pieces, ccp_text=11, extra=utf16 + comp)

    assert doc.body == "Hello World"
    assert doc.ccp_text == 11
    assert len(doc.pieces) == 2
    assert doc.fc_for_cp(0) == u_wd
    assert doc.fc_for_cp(6) == 2 * c_wd
    assert doc.warnings == []


def test_piece_table_all_compressed():
    text = b"abcde"
    fib_size = 512
    c_wd = fib_size

    doc = make_pcd_doc([(0, 5, 0x40000000 | (2 * c_wd), True)], ccp_text=5, extra=text)

    assert doc.body == "abcde"


def test_fallback_scrape_when_no_clx():
    marker = b"HELLOSCRAPEWORLD"
    wd = make_fib(ccp_text=1000, fc_clx=0, lcb_clx=0) + marker
    cfb = build_cfb({"WordDocument": wd, "1Table": b"\x00" * 16})

    doc = DocReader(OLE2Reader(cfb))

    assert marker.decode("ascii") in doc.body
    assert any("CLX" in w or "scrape" in w for w in doc.warnings)


def test_simple_utf16_text_without_clx():
    text = "Hi\r".encode("utf-16le")
    text_off = 512
    wd = bytearray(
        make_fib(
            ccp_text=3,
            fc_clx=0,
            lcb_clx=0,
            f_complex=False,
            fc_min=text_off,
            fc_mac=text_off + len(text),
        )
    )
    wd[text_off : text_off + len(text)] = text
    cfb = build_cfb({"WordDocument": bytes(wd)})

    doc = DocReader(OLE2Reader(cfb))

    assert doc.body == "Hi\r"
    assert doc.fc_for_cp(1) == text_off + 2
    assert any("simple" in w for w in doc.warnings)


def test_simple_compressed_text_without_clx():
    text = b"Price \xa310\r"
    text_off = 512
    wd = bytearray(
        make_fib(
            ccp_text=len(text),
            fc_clx=0,
            lcb_clx=0,
            f_complex=False,
            fc_min=text_off,
            fc_mac=text_off + len(text),
        )
    )
    wd[text_off : text_off + len(text)] = text
    cfb = build_cfb({"WordDocument": bytes(wd)})

    doc = DocReader(OLE2Reader(cfb))

    assert doc.body == "Price \u00a310\r"
    assert doc.fc_for_cp(6) == 2 * (text_off + 6)
