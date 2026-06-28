"""Tests for public conversion helpers and the CLI entry point."""
from __future__ import annotations

from io import BytesIO
import zipfile

import doc2md

from cfb import build_cfb
from word_docs import make_fib, make_simple_doc_bytes


def test_convert_path_reads_simple_doc(tmp_path):
    path = tmp_path / "simple.doc"
    path.write_bytes(make_simple_doc_bytes("Hello\rWorld\r"))

    text = doc2md.convert_path(path)

    assert text == "Hello\n\nWorld"


def test_plain_mode_uses_text_line_breaks(tmp_path):
    path = tmp_path / "simple.doc"
    path.write_bytes(make_simple_doc_bytes("Hello\rWorld\r"))

    text = doc2md.convert_path(path, plain=True)

    assert text == "Hello\nWorld"


def test_convert_bytes_reads_markdown_table():
    table_text = "Name\x07Value\x07\rRevenue\x07100\x07\r"
    doc_bytes = _make_complex_doc_bytes(table_text)

    text = doc2md.convert_bytes(doc_bytes)

    assert "| Name | Value |" in text
    assert "| Revenue | 100 |" in text


def test_convert_bytes_reads_textbox_story_tables():
    main = "Main\r"
    textbox = "TABLE I\rName\x07Value\x07\rAssets\x07100\x07\r"
    doc_bytes = _make_complex_doc_bytes(
        main + textbox,
        ccp_text=len(main),
        ccp_txbx=len(textbox),
    )

    text = doc2md.convert_bytes(doc_bytes)

    assert text.startswith("Main")
    assert "TABLE I" in text
    assert "| Name | Value |" in text
    assert "| Assets | 100 |" in text


def test_main_writes_output_file(tmp_path):
    input_path = tmp_path / "simple.doc"
    output_path = tmp_path / "out.md"
    input_path.write_bytes(make_simple_doc_bytes("Hello\r"))

    assert doc2md.main([str(input_path), "-o", str(output_path)]) == 0
    assert output_path.read_text(encoding="utf-8") == "Hello\n"


def test_convert_bytes_reads_html_saved_as_doc():
    html = (
        b'<!doctype html><html><head><title>Skip me</title></head><body>'
        b"<h1>Inside MCC</h1><p>Transforming Ourselves.</p>"
        b"<script>window.location.href='/lander'</script></body></html>"
    )
    warnings: list[str] = []

    text = doc2md.convert_bytes(html, warn=warnings.append)

    assert text == "Inside MCC\n\nTransforming Ourselves."
    assert any("HTML" in warning for warning in warnings)


def test_convert_bytes_renders_html_tables_saved_as_doc():
    html = (
        b"<!doctype html><html><body><p>Before</p><table>"
        b"<tr><th>Name</th><th>Value</th></tr>"
        b"<tr><td>Assets</td><td>100</td></tr>"
        b"</table><p>After</p></body></html>"
    )

    text = doc2md.convert_bytes(html)

    assert "Before" in text
    assert "| Name | Value |" in text
    assert "| Assets | 100 |" in text
    assert text.endswith("After")


def test_convert_bytes_reads_docx_saved_as_doc():
    xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Report</w:t></w:r></w:p>
    <w:p><w:r><w:t>Hello</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t>World</w:t></w:r></w:p>
    <w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>Revenue</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>100</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl>
  </w:body>
</w:document>"""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", xml)
    warnings: list[str] = []

    text = doc2md.convert_bytes(buf.getvalue(), warn=warnings.append)

    assert "# Report" in text
    assert "Hello\tWorld" in text
    assert "| Revenue | 100 |" in text
    assert any("OOXML" in warning for warning in warnings)


def test_convert_bytes_reads_rtf_saved_as_doc():
    warnings: list[str] = []

    text = doc2md.convert_bytes(
        br"{\rtf1\ansi Hello\par World\tab \'93quoted\'94}",
        warn=warnings.append,
    )

    assert text == "Hello\n\nWorld\t“quoted”"
    assert any("RTF" in warning for warning in warnings)


def test_convert_bytes_empty_input_returns_empty():
    warnings: list[str] = []

    assert doc2md.convert_bytes(b"", warn=warnings.append) == ""
    assert any("empty" in warning for warning in warnings)


def _make_complex_doc_bytes(
    text: str,
    ccp_text: int | None = None,
    ccp_txbx: int = 0,
) -> bytes:
    encoded = text.encode("cp1252")
    text_off = 512
    fc_compressed = 0x40000000 | (2 * text_off)
    cp_count = len(text)
    if ccp_text is None:
        ccp_text = cp_count

    plc = bytearray()
    plc.extend((0).to_bytes(4, "little"))
    plc.extend(cp_count.to_bytes(4, "little"))
    pcd = bytearray(8)
    pcd[2:6] = fc_compressed.to_bytes(4, "little")
    plc.extend(pcd)

    clx = bytearray(b"\x02")
    clx.extend(len(plc).to_bytes(4, "little", signed=True))
    clx.extend(plc)

    wd = bytearray(
        make_fib(
            ccp_text,
            fc_clx=0,
            lcb_clx=len(clx),
            ccp_txbx=ccp_txbx,
        )
    )
    wd[text_off : text_off + len(encoded)] = encoded
    return build_cfb({"WordDocument": bytes(wd), "1Table": bytes(clx)})
