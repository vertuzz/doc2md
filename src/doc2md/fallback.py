"""Fallback readers for Word-compatible files that are not OLE2 ``.doc``.

Some public files use a ``.doc`` suffix while actually containing HTML, RTF, or
OOXML/``.docx`` bytes. LibreOffice accepts those as Word-compatible inputs, so
we provide lightweight stdlib-only text fallbacks before the strict OLE2 path.
"""
from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
import codecs
import re
import zipfile
import xml.etree.ElementTree as ET

from . import tables

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"

ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
HTML_PREFIXES = (
    b"<!doctype html",
    b"<html",
    b"<head",
    b"<body",
    b"<?xml",
)


def convert_alternate_bytes(data: bytes, plain: bool = False, warn=None) -> str | None:
    """Return converted text for non-OLE Word-compatible bytes, or ``None``.

    ``None`` means the input is not a recognised alternate container and should
    continue through the normal binary ``.doc`` parser.
    """
    warn = warn or (lambda _msg: None)
    if not data:
        warn("empty input; returning empty output")
        return ""

    stripped = _strip_leading_bom(data).lstrip()
    lowered = stripped[:128].lower()

    if data.startswith(ZIP_SIGNATURES):
        converted = _convert_ooxml_word(data, plain=plain, warn=warn)
        if converted is not None:
            return converted

    if lowered.startswith(HTML_PREFIXES) and b"<html" in lowered[:128]:
        warn("input is HTML, not legacy OLE2 .doc; using HTML text fallback")
        return _convert_html(data)

    if lowered.startswith(b"{\\rtf"):
        warn("input is RTF, not legacy OLE2 .doc; using RTF text fallback")
        return _convert_rtf(data)

    return None


def _strip_leading_bom(data: bytes) -> bytes:
    for bom in (codecs.BOM_UTF8, codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
        if data.startswith(bom):
            return data[len(bom):]
    return data


def _join_blocks(blocks: list[str], plain: bool) -> str:
    blocks = [block.strip() for block in blocks if block and block.strip()]
    if plain:
        return "\n".join(blocks)
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------- OOXML
def _convert_ooxml_word(data: bytes, plain: bool, warn) -> str | None:
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            names = set(zf.namelist())
            if "word/document.xml" not in names:
                return None
            xml_bytes = zf.read("word/document.xml")
    except zipfile.BadZipFile:
        return None
    except OSError as exc:
        warn(f"OOXML fallback failed ({exc}); returning empty output")
        return ""

    warn("input is OOXML/ZIP, not legacy OLE2 .doc; using OOXML text fallback")
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        warn(f"OOXML document.xml parse failed ({exc}); returning empty output")
        return ""

    body = root.find(f"{W}body")
    if body is None:
        return ""

    blocks: list[str] = []
    for child in body:
        if child.tag == f"{W}p":
            rendered = _render_docx_paragraph(child, plain=plain)
            if rendered:
                blocks.append(rendered)
        elif child.tag == f"{W}tbl":
            rendered = _render_docx_table(child)
            if rendered:
                blocks.append(rendered)
    return _join_blocks(blocks, plain=plain)


def _attr(elem: ET.Element, name: str) -> str | None:
    return elem.get(f"{W}{name}") or elem.get(name)


def _docx_paragraph_style(p: ET.Element) -> str:
    p_pr = p.find(f"{W}pPr")
    if p_pr is None:
        return ""
    p_style = p_pr.find(f"{W}pStyle")
    if p_style is None:
        return ""
    return _attr(p_style, "val") or ""


def _docx_is_numbered(p: ET.Element) -> bool:
    p_pr = p.find(f"{W}pPr")
    return p_pr is not None and p_pr.find(f"{W}numPr") is not None


def _docx_paragraph_text(p: ET.Element) -> str:
    out: list[str] = []
    for elem in p.iter():
        if elem.tag == f"{W}t":
            out.append(elem.text or "")
        elif elem.tag == f"{W}tab":
            out.append("\t")
        elif elem.tag in (f"{W}br", f"{W}cr"):
            out.append("\n")
        elif elem.tag == f"{W}noBreakHyphen":
            out.append("-")
        elif elem.tag == f"{W}softHyphen":
            continue
        elif elem.tag == f"{W}sym":
            char = _attr(elem, "char")
            if char:
                try:
                    out.append(chr(int(char, 16)))
                except ValueError:
                    pass
    return "".join(out)


def _render_docx_paragraph(p: ET.Element, plain: bool) -> str:
    text = _docx_paragraph_text(p).strip()
    if not text:
        return ""
    if plain:
        return text

    style = re.sub(r"[\s_-]+", "", _docx_paragraph_style(p)).lower()
    heading = re.match(r"heading([1-9])$", style)
    if heading:
        level = min(int(heading.group(1)), 6)
        return f"{'#' * level} {text}"
    if style == "title":
        return f"# {text}"
    if _docx_is_numbered(p):
        return f"- {text}"
    return text


def _docx_cell_text(tc: ET.Element) -> str:
    parts = []
    for p in tc.iter(f"{W}p"):
        text = _docx_paragraph_text(p).strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def _render_docx_table(tbl: ET.Element) -> str:
    rows: list[list[str]] = []
    for tr in tbl.findall(f"{W}tr"):
        row = [_docx_cell_text(tc) for tc in tr.findall(f"{W}tc")]
        if row:
            rows.append(row)
    return tables.render_markdown_table(rows)


# ----------------------------------------------------------------------- HTML
def _decode_text_bytes(data: bytes) -> str:
    if data.startswith(codecs.BOM_UTF8):
        return data.decode("utf-8-sig", "replace")
    if data.startswith(codecs.BOM_UTF16_LE):
        return data.decode("utf-16le", "replace")
    if data.startswith(codecs.BOM_UTF16_BE):
        return data.decode("utf-16be", "replace")

    head = data[:4096].decode("ascii", "ignore")
    match = re.search(r"charset\s*=\s*['\"]?([A-Za-z0-9._-]+)", head, re.I)
    encodings = [match.group(1)] if match else []
    encodings.extend(["utf-8", "cp1252"])
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", "replace")


class _HTMLTextExtractor(HTMLParser):
    _skip_tags = {"script", "style", "head"}
    _block_tags = {
        "address",
        "article",
        "aside",
        "blockquote",
        "body",
        "dd",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.table_depth = 0
        self.current_table: list[list[str]] | None = None
        self.current_row: list[str] | None = None
        self.current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001 - stdlib signature
        tag = tag.lower()
        if tag in self._skip_tags:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if self.table_depth:
            self._handle_table_starttag(tag)
            return
        if tag == "table":
            self._append_break()
            self.table_depth = 1
            self.current_table = []
            return
        if tag == "br":
            self._append_break(single=True)
        elif tag in self._block_tags:
            self._append_break()
            if tag == "li":
                self._append_text("- ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._skip_tags and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if self.table_depth:
            self._handle_table_endtag(tag)
            return
        if tag in self._block_tags:
            self._append_break()

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if self.table_depth:
            if self.current_cell is not None:
                self.current_cell.append(data)
            return
        self._append_text(data)

    def _handle_table_starttag(self, tag: str) -> None:
        if tag == "table":
            self.table_depth += 1
            return
        if self.table_depth != 1:
            return
        if tag == "tr":
            self.current_row = []
        elif tag in {"td", "th"}:
            if self.current_row is None:
                self.current_row = []
            self.current_cell = []
        elif tag == "br" and self.current_cell is not None:
            self.current_cell.append(" ")
        elif tag in self._block_tags and self.current_cell is not None:
            self.current_cell.append(" ")

    def _handle_table_endtag(self, tag: str) -> None:
        if tag == "table":
            if self.table_depth > 1:
                self.table_depth -= 1
                return
            self._close_table_row()
            rendered = tables.render_markdown_table(self.current_table or [])
            if rendered:
                self.parts.append(rendered)
                self._append_break()
            self.table_depth = 0
            self.current_table = None
            self.current_row = None
            self.current_cell = None
            return

        if self.table_depth != 1:
            return
        if tag in {"td", "th"}:
            self._close_table_cell()
        elif tag == "tr":
            self._close_table_row()
        elif tag in self._block_tags and self.current_cell is not None:
            self.current_cell.append(" ")

    def _close_table_cell(self) -> None:
        if self.current_cell is None:
            return
        if self.current_row is None:
            self.current_row = []
        text = re.sub(r"\s+", " ", "".join(self.current_cell)).strip()
        self.current_row.append(text)
        self.current_cell = None

    def _close_table_row(self) -> None:
        self._close_table_cell()
        if self.current_row is None:
            return
        if self.current_table is None:
            self.current_table = []
        if any(cell.strip() for cell in self.current_row):
            self.current_table.append(self.current_row)
        self.current_row = None

    def _append_text(self, text: str) -> None:
        text = re.sub(r"\s+", " ", text)
        if not text.strip():
            return
        if self.parts and not self.parts[-1].endswith((" ", "\n", "\t")):
            self.parts.append(" ")
        self.parts.append(text.strip())

    def _append_break(self, single: bool = False) -> None:
        if not self.parts:
            return
        marker = "\n" if single else "\n\n"
        current = "".join(self.parts)
        if current.endswith(marker):
            return
        if current.endswith("\n") and not single:
            self.parts.append("\n")
        elif not current.endswith("\n"):
            self.parts.append(marker)

    def text(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _convert_html(data: bytes) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(_decode_text_bytes(data))
    parser.close()
    return parser.text()


# ------------------------------------------------------------------------ RTF
_RTF_DESTINATIONS = {
    "annotation",
    "author",
    "colortbl",
    "comment",
    "datafield",
    "fonttbl",
    "footer",
    "footerf",
    "footerl",
    "footerr",
    "header",
    "headerf",
    "headerl",
    "headerr",
    "info",
    "object",
    "pict",
    "revtbl",
    "stylesheet",
    "xmlopen",
    "xmlattr",
    "xmlclose",
}

_RTF_SPECIALS = {
    "bullet": "*",
    "emdash": "--",
    "endash": "-",
    "ldblquote": '"',
    "rdblquote": '"',
    "lquote": "'",
    "rquote": "'",
    "u8211": "-",
    "u8212": "--",
}


@dataclass
class _RTFState:
    skip: bool = False
    uc: int = 1

    def copy(self) -> "_RTFState":
        return _RTFState(skip=self.skip, uc=self.uc)


def _convert_rtf(data: bytes) -> str:
    text = data.decode("latin1", "replace")
    out: list[str] = []
    stack: list[_RTFState] = []
    state = _RTFState()
    ignorable_next_group = False
    i = 0
    n = len(text)

    def append(value: str) -> None:
        if not state.skip:
            out.append(value)

    while i < n:
        ch = text[i]
        if ch == "{":
            stack.append(state)
            state = state.copy()
            if ignorable_next_group:
                state.skip = True
                ignorable_next_group = False
            i += 1
            continue
        if ch == "}":
            state = stack.pop() if stack else _RTFState()
            i += 1
            continue
        if ch != "\\":
            if ord(ch) >= 0x20:
                append(ch)
            i += 1
            continue

        i += 1
        if i >= n:
            break
        escaped = text[i]
        if escaped in "\\{}":
            append(escaped)
            i += 1
            continue
        if escaped == "*":
            ignorable_next_group = True
            i += 1
            continue
        if escaped == "'":
            if i + 2 < n:
                try:
                    append(bytes.fromhex(text[i + 1:i + 3]).decode("cp1252", "replace"))
                except ValueError:
                    pass
                i += 3
            else:
                i += 1
            continue

        start = i
        while i < n and text[i].isalpha():
            i += 1
        word = text[start:i]
        sign = 1
        if i < n and text[i] in "+-":
            sign = -1 if text[i] == "-" else 1
            i += 1
        num_start = i
        while i < n and text[i].isdigit():
            i += 1
        param = None
        if i > num_start:
            param = sign * int(text[num_start:i])
        if i < n and text[i] == " ":
            i += 1

        if not word:
            continue
        if word in _RTF_DESTINATIONS:
            state.skip = True
        elif word == "uc" and param is not None:
            state.uc = max(0, param)
        elif word == "u" and param is not None:
            if param < 0:
                param += 65536
            append(chr(param))
            i = min(n, i + state.uc)
        elif word == "par":
            append("\n\n")
        elif word in ("line", "page"):
            append("\n")
        elif word == "tab":
            append("\t")
        elif word in _RTF_SPECIALS:
            append(_RTF_SPECIALS[word])

    converted = "".join(out)
    converted = re.sub(r"[ \t]+\n", "\n", converted)
    converted = re.sub(r"\n{3,}", "\n\n", converted)
    return converted.strip()
