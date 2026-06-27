"""Tests for public conversion helpers and the CLI entry point."""
from __future__ import annotations

import doc2markdown

from cfb import build_cfb
from word_docs import make_fib, make_simple_doc_bytes


def test_convert_path_reads_simple_doc(tmp_path):
    path = tmp_path / "simple.doc"
    path.write_bytes(make_simple_doc_bytes("Hello\rWorld\r"))

    text = doc2markdown.convert_path(path)

    assert text == "Hello\n\nWorld"


def test_convert_bytes_reads_markdown_table():
    table_text = "Name\x07Value\x07\rRevenue\x07100\x07\r"
    doc_bytes = _make_complex_doc_bytes(table_text)

    text = doc2markdown.convert_bytes(doc_bytes)

    assert "| Name | Value |" in text
    assert "| Revenue | 100 |" in text


def test_main_writes_output_file(tmp_path):
    input_path = tmp_path / "simple.doc"
    output_path = tmp_path / "out.md"
    input_path.write_bytes(make_simple_doc_bytes("Hello\r"))

    assert doc2markdown.main([str(input_path), "-o", str(output_path)]) == 0
    assert output_path.read_text(encoding="utf-8") == "Hello\n"


def _make_complex_doc_bytes(text: str) -> bytes:
    encoded = text.encode("cp1252")
    text_off = 512
    fc_compressed = 0x40000000 | (2 * text_off)
    cp_count = len(text)

    plc = bytearray()
    plc.extend((0).to_bytes(4, "little"))
    plc.extend(cp_count.to_bytes(4, "little"))
    pcd = bytearray(8)
    pcd[2:6] = fc_compressed.to_bytes(4, "little")
    plc.extend(pcd)

    clx = bytearray(b"\x02")
    clx.extend(len(plc).to_bytes(4, "little", signed=True))
    clx.extend(plc)

    wd = bytearray(make_fib(cp_count, fc_clx=0, lcb_clx=len(clx)))
    wd[text_off : text_off + len(encoded)] = encoded
    return build_cfb({"WordDocument": bytes(wd), "1Table": bytes(clx)})
