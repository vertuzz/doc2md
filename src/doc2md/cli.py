"""Command line interface and public conversion helpers.

Usage:
    doc2md INPUT.doc            # write Markdown to stdout
    doc2md INPUT.doc -o out.md  # write to a file
    doc2md INPUT.doc --plain    # text + tables, no inline markup

Warnings are written to stderr; a non-zero exit code signals a fatal error.
Zero third-party dependencies; stdlib only.
"""
from __future__ import annotations

import argparse
from os import PathLike
from pathlib import Path
import sys
from typing import Callable

from . import tables
from .docreader import DocError, DocReader
from .formatting import Formatting
from .ole2 import OLE2Reader, OLEError

WarnFunc = Callable[[str], None]

# Control characters in the decoded text stream.
C_TAB = "\t"
C_CELL = "\x07"
C_LINE = "\x0b"
C_PAGE = "\x0c"
C_PARA = "\r"


def _clean_run(text: str) -> str:
    """Normalise control characters inside a paragraph.

    Field instructions (between 0x13 and 0x14) are dropped; field results
    (between 0x14 and 0x15) are kept, so hyperlink display text survives without
    the ``HYPERLINK "..."`` instruction leaking into the output. Other control
    characters are mapped to their Markdown/plain equivalents or discarded.
    """
    out = []
    in_result: list[bool] = []  # one entry per open field level
    for ch in text:
        o = ord(ch)
        if o == 0x13:  # field begin
            in_result.append(False)
            continue
        if o == 0x14:  # field separator -> now the field result
            if in_result:
                in_result[-1] = True
            continue
        if o == 0x15:  # field end
            if in_result:
                in_result.pop()
            continue
        # Keep text only outside any field or inside a field result.
        if in_result and not in_result[-1]:
            continue
        if o == 0x0B:
            out.append("\n")
        elif o == 0x0C:
            out.append("\n---\n")
        elif o == 0x09:
            out.append("\t")
        elif o == 0x07:
            out.append(" ")
        elif o == 0x0A:
            out.append("\n")
        elif o < 0x20 or o == 0x7F:
            continue
        else:
            out.append(ch)
    return "".join(out)


def _segments(body: str) -> list[tuple[int, str, int]]:
    """Split the body on paragraph marks (``0x0D``).

    Returns a list of ``(mark_cp, text, start_cp)`` where ``mark_cp`` is the CP of
    the terminating paragraph mark (or ``len(body)`` for the trailing fragment)
    and ``text`` is the fragment that precedes it.
    """
    segs: list[tuple[int, str, int]] = []
    start = 0
    for i, ch in enumerate(body):
        if ch == C_PARA:
            segs.append((i, body[start:i], start))
            start = i + 1
    if start < len(body):
        segs.append((len(body), body[start:], start))
    return segs


def _in_table(text: str, mark_cp: int, fmt: Formatting | None) -> bool:
    """Return whether a segment belongs to a table."""
    if C_CELL in text:
        return True
    if fmt is not None and fmt.available:
        try:
            return fmt.pap_for_cp(mark_cp).f_in_table
        except Exception:
            return False
    return False


def _render_table_block(block: list[str]) -> str:
    """Render a group of in-table paragraph fragments as a Markdown table."""
    segmented_rows = tables.chunk_segmented_cells(block)
    if segmented_rows is not None:
        return tables.render_markdown_table(segmented_rows)

    joined = "\r".join(block)
    cells = joined.split(C_CELL)
    ncols = tables.detect_column_count(cells)
    rows = tables.chunk_cells(cells, ncols)
    return tables.render_markdown_table(rows)


def _wrap_inline(text: str, bold: bool, italic: bool) -> str:
    """Wrap a text chunk with Markdown emphasis markers."""
    if not text:
        return ""
    stripped = text.strip(" ")
    if not stripped:
        return text
    lead = text[: len(text) - len(text.lstrip(" "))]
    trail = text[len(text.rstrip(" ")) :]
    core = text[len(lead) : len(text) - len(trail)] if trail else stripped
    if bold and italic:
        core = f"**_{core}_**"
    elif bold:
        core = f"**{core}**"
    elif italic:
        core = f"_{core}_"
    return lead + core + trail


def _render_inline(text: str, start_cp: int, fmt: Formatting) -> str:
    """Render a paragraph fragment with field handling and inline formatting."""
    out: list[str] = []
    buf: list[str] = []
    cur = (False, False)
    in_result: list[bool] = []

    def flush() -> None:
        if buf:
            out.append(_wrap_inline("".join(buf), cur[0], cur[1]))
            buf.clear()

    for offset, ch in enumerate(text):
        o = ord(ch)
        cp = start_cp + offset
        if o == 0x13:  # field begin
            flush()
            in_result.append(False)
            continue
        if o == 0x14:  # field separator
            flush()
            if in_result:
                in_result[-1] = True
            continue
        if o == 0x15:  # field end
            flush()
            if in_result:
                in_result.pop()
            continue
        chp = fmt.chp_for_cp(cp)
        state = (chp.bold, chp.italic)
        if state != cur:
            flush()
            cur = state
        visible = not (in_result and not in_result[-1])
        if not visible:
            continue
        if o == 0x0B:
            buf.append("\n")
        elif o == 0x0C:
            buf.append("\n---\n")
        elif o == 0x09:
            buf.append("\t")
        elif o == 0x07:
            buf.append(" ")
        elif o == 0x0A:
            buf.append("\n")
        elif o < 0x20 or o == 0x7F:
            continue
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def _render_paragraph(
    text: str,
    start_cp: int,
    mark_cp: int,
    fmt: Formatting | None,
    plain: bool,
) -> str:
    """Render a non-table paragraph fragment."""
    if plain or fmt is None or not fmt.available:
        return _clean_run(text).strip()

    body = _render_inline(text, start_cp, fmt).strip()
    if not body:
        return ""
    try:
        pap = fmt.pap_for_cp(mark_cp)
    except Exception:
        pap = None

    if pap is not None and pap.outline_level is not None and 0 <= pap.outline_level <= 8:
        level = min(pap.outline_level, 5)
        return f"{'#' * (level + 1)} {body}"

    if pap is not None and pap.ilfo not in (0, 0xF801):
        indent = "  " * min(pap.ilvl, 8)
        return f"{indent}- {body}"

    return body


def render(doc: DocReader, fmt: Formatting | None, plain: bool = False) -> str:
    """Render a parsed Word document body to Markdown or plain text."""
    body = doc.body
    segs = _segments(body)
    out_parts: list[str] = []

    i = 0
    n = len(segs)
    while i < n:
        mark_cp, text, start = segs[i]
        if _in_table(text, mark_cp, fmt):
            block: list[tuple[int, str, int]] = []
            while i < n and _in_table(segs[i][1], segs[i][0], fmt):
                block.append(segs[i])
                i += 1
            if any(C_CELL in frag for _, frag, _ in block):
                rendered = _render_table_block([frag for _, frag, _ in block])
                if rendered:
                    out_parts.append(rendered)
            else:
                for block_mark_cp, frag, block_start in block:
                    cleaned = _render_paragraph(frag, block_start, block_mark_cp, fmt, plain)
                    if cleaned:
                        out_parts.append(cleaned)
        else:
            cleaned = _render_paragraph(text, start, mark_cp, fmt, plain)
            if cleaned:
                out_parts.append(cleaned)
            i += 1
    return "\n\n".join(out_parts)


def convert_bytes(data: bytes, plain: bool = False, warn: WarnFunc | None = None) -> str:
    """Convert Word 97-2003 ``.doc`` bytes to Markdown or plain text."""
    warn = warn or (lambda _msg: None)
    ole = OLE2Reader(data)
    doc = DocReader(ole, warn=warn)
    fmt: Formatting | None = None
    try:
        fmt = Formatting(doc, warn=warn)
    except Exception as exc:  # pragma: no cover - defensive
        warn(f"formatting parser failed ({exc}); continuing without tables/markup")
        fmt = None
    return render(doc, fmt, plain)


def convert_path(
    path: str | PathLike[str],
    plain: bool = False,
    warn: WarnFunc | None = None,
) -> str:
    """Convert a Word 97-2003 ``.doc`` file to Markdown or plain text."""
    return convert_bytes(Path(path).read_bytes(), plain=plain, warn=warn)


def convert(path: str | PathLike[str], plain: bool = False, warn: WarnFunc | None = None) -> str:
    """Alias for :func:`convert_path`."""
    return convert_path(path, plain=plain, warn=warn)


def _write_stdout(text: str) -> None:
    sys.stdout.buffer.write(text.encode("utf-8"))
    if not text.endswith("\n"):
        sys.stdout.buffer.write(b"\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="doc2md",
        description="Convert Word 97-2003 .doc to text/Markdown.",
    )
    parser.add_argument("input", help="path to a .doc file")
    parser.add_argument("-o", "--output", help="write output to this file instead of stdout")
    parser.add_argument("--plain", action="store_true", help="emit plain text (no Markdown markup)")
    args = parser.parse_args(argv)

    def warn(msg: str) -> None:
        print(f"warning: {msg}", file=sys.stderr)

    try:
        text = convert_path(args.input, plain=args.plain, warn=warn)
    except (OLEError, DocError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print(f"error: file not found: {args.input}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: cannot read/write file: {exc}", file=sys.stderr)
        return 1

    if args.output and args.output != "-":
        try:
            with Path(args.output).open("w", encoding="utf-8", newline="\n") as f:
                f.write(text)
                if not text.endswith("\n"):
                    f.write("\n")
        except OSError as exc:
            print(f"error: cannot write output: {exc}", file=sys.stderr)
            return 1
    else:
        _write_stdout(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
