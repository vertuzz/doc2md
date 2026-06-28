"""Table grouping and Markdown pipe-table rendering for ``.doc`` conversion.

Tables are detected from runs of cell marks (``0x07``) in the text stream. Row
boundaries are taken from paragraph marks (``0x0D``) when present; when a table
is a single paragraph containing many cell marks (a common layout-table shape
that omits per-row terminating marks), a column-count heuristic splits the flat
cell list into rows. Output is GitHub-flavoured Markdown pipe tables.
"""
from __future__ import annotations

C_CELL = "\x07"
C_PARA = "\r"

# Cells are chunked into at most this many columns by the heuristic.
_MAX_COLS = 24


def _is_empty_cell(cell: str) -> bool:
    return cell.strip() == ""


def _without_final_split_cell(cells: list[str]) -> list[str]:
    """Drop the synthetic empty item produced by splitting a trailing cell mark."""
    if cells and _is_empty_cell(cells[-1]):
        return cells[:-1]
    return cells


def _chunk_by_row_markers(cells: list[str], ncols: int) -> list[list[str]] | None:
    """Chunk rows when every row has an extra empty terminator cell."""
    if ncols < 1:
        return None
    effective = _without_final_split_cell(cells)
    group = ncols + 1
    if len(effective) < group * 2 or len(effective) % group:
        return None
    rows: list[list[str]] = []
    for start in range(0, len(effective), group):
        row = effective[start : start + ncols]
        terminator = effective[start + ncols]
        if not _is_empty_cell(terminator):
            return None
        rows.append(row)
    if not any(any(not _is_empty_cell(cell) for cell in row) for row in rows):
        return None
    return rows


def _chunk_by_offset_row_markers(cells: list[str], ncols: int) -> list[list[str]] | None:
    """Chunk rows when a short prefix precedes regular row terminator cells.

    Some older Word layout tables store a title/caption in the first few cells
    and then continue with rows shaped as ``ncols`` cells plus an empty cell
    marker. LibreOffice treats those as normal rows; preserving the prefix keeps
    the title while allowing the data area to be split into readable rows.
    """
    if ncols < 1:
        return None
    effective = _without_final_split_cell(cells)
    group = ncols + 1
    if len(effective) < group * 2:
        return None

    max_offset = min(len(effective) - group * 2, _MAX_COLS)
    for offset in range(1, max_offset + 1):
        rest = effective[offset:]
        if len(rest) < group * 2 or len(rest) % group:
            continue
        rows: list[list[str]] = []
        prefix = effective[:offset]
        prefix_nonempty = [cell for cell in prefix if not _is_empty_cell(cell)]
        if prefix_nonempty:
            rows.append(prefix_nonempty)
        valid = True
        for start in range(0, len(rest), group):
            row = rest[start : start + ncols]
            terminator = rest[start + ncols]
            if not _is_empty_cell(terminator):
                valid = False
                break
            rows.append(row)
        if not valid:
            continue
        data_rows = rows[1:] if prefix_nonempty else rows
        if len(data_rows) < 2:
            continue
        if not any(any(not _is_empty_cell(cell) for cell in row) for row in data_rows):
            continue
        return rows
    return None


def clean_cell(text: str) -> str:
    """Clean a cell's text for Markdown: drop field instructions, collapse
    control characters to spaces, escape pipe characters."""
    out = []
    in_result: list[bool] = []
    for ch in text:
        o = ord(ch)
        if o == 0x13:
            in_result.append(False)
            continue
        if o == 0x14:
            if in_result:
                in_result[-1] = True
            continue
        if o == 0x15:
            if in_result:
                in_result.pop()
            continue
        if in_result and not in_result[-1]:
            continue
        if o in (0x0A, 0x0B, 0x0C, 0x0D, 0x09, 0x07):
            out.append(" ")
        elif o < 0x20 or o == 0x7F:
            continue
        else:
            out.append(ch)
    return "".join(out).replace("|", "\\|").strip()


def _is_label(cell: str) -> bool:
    """A row is likely a data row if its first cell looks like a row label."""
    c = cell.strip()
    if not c:
        return False
    return c.isdigit() or len(c) <= 3


def _looks_numeric_cell(cell: str) -> bool:
    """Return true for accounting-style values, years and percentages."""
    c = cell.strip()
    if not c or not any(ch.isdigit() for ch in c):
        return False
    allowed = set("$0123456789,.-()%/ ")
    currency_codepoints = {0x00A3, 0x00A5, 0x20AC}
    plausible = sum(
        1
        for ch in c
        if ch in allowed or ch.isspace() or ord(ch) in currency_codepoints
    )
    return plausible / len(c) >= 0.8


def _row_likeness(row: list[str]) -> float:
    """Score how much a candidate row resembles a structured table row."""
    if not any(not _is_empty_cell(cell) for cell in row):
        return 0.0

    first = row[0].strip()
    rest = row[1:]
    non_empty_rest = sum(1 for cell in rest if not _is_empty_cell(cell))
    numeric_rest = sum(1 for cell in rest if _looks_numeric_cell(cell))
    text_rest = non_empty_rest - numeric_rest
    first_numeric = _looks_numeric_cell(first)

    if _is_label(first) and not (first_numeric and numeric_rest):
        return 1.0
    if first and not first_numeric and numeric_rest >= 2:
        return 1.0 if text_rest == 0 else 0.35
    if not first and numeric_rest >= 2:
        return 0.8
    if first and not first_numeric and numeric_rest == 1 and non_empty_rest <= 3:
        return 0.7
    if first and not first_numeric and len(first) <= 40 and non_empty_rest >= 2:
        return 0.45
    return 0.0


def detect_column_count(cells: list[str]) -> int:
    """Heuristically determine the column count for a flat cell list.

    First detects the common Word shape where each row ends with an extra empty
    cell mark. Then tries every divisor ``n`` (2..16) of the cell count
    (optionally dropping a single trailing empty cell) and keeps the layout
    where the most rows begin with a short label-like first cell. Falls back to
    a single row when no layout is clearly row-like.
    """
    m = len(cells)
    if m <= 1:
        return m

    best_marker: tuple[int, int] | None = None
    for ncols in range(1, min(m, _MAX_COLS) + 1):
        rows = _chunk_by_row_markers(cells, ncols)
        if rows is None:
            rows = _chunk_by_offset_row_markers(cells, ncols)
        if rows is None:
            continue
        n_rows = len(rows)
        if best_marker is None or n_rows > best_marker[0] or (
            n_rows == best_marker[0] and ncols < best_marker[1]
        ):
            best_marker = (n_rows, ncols)
    if best_marker is not None:
        return best_marker[1]

    candidates = [m]
    if _is_empty_cell(cells[-1]):
        candidates.append(m - 1)
    best_n = m
    best_score = -1.0
    for total in candidates:
        if total < 4:
            continue
        for n in range(2, min(total, _MAX_COLS) + 1):
            if total % n:
                continue
            n_rows = total // n
            if n_rows < 2:
                continue
            row_score = 0.0
            for r in range(n_rows):
                row_score += _row_likeness(cells[r * n : (r + 1) * n])
            score = row_score / n_rows
            if score > best_score or (score == best_score and n < best_n):
                best_score = score
                best_n = n
    if best_score >= 0.5 and best_n < m:
        return best_n
    return m


def chunk_cells(cells: list[str], ncols: int) -> list[list[str]]:
    """Split a flat cell list into rows of ``ncols`` columns, trimming a single
    trailing empty cell or regular row-terminator cells when present."""
    total = len(cells)
    if ncols <= 0:
        return []
    rows = _chunk_by_row_markers(cells, ncols)
    if rows is None:
        rows = _chunk_by_offset_row_markers(cells, ncols)
    if rows is not None:
        return rows
    if ncols >= total:
        return [cells]
    # Drop a trailing empty cell so the remaining count divides evenly.
    if cells and _is_empty_cell(cells[-1]) and total % ncols == 1:
        cells = cells[:-1]
        total -= 1
    rows = [cells[r * ncols : (r + 1) * ncols] for r in range(total // ncols)]
    return rows


def chunk_segmented_cells(fragments: list[str]) -> list[list[str]] | None:
    """Split a table block into rows using paragraph-level cell-mark segments.

    Many real Word layout tables store each visual row as a paragraph fragment
    that already contains that row's cell marks. Flattening the whole block
    first can turn those tables into one very wide Markdown row, especially when
    the row width is greater than the heuristic cap. This path keeps those
    paragraph boundaries as row hints while still appending cell-internal
    paragraphs to the nearest cell.
    """
    rows: list[list[str]] = []
    pending_before_first_row: list[str] = []
    marked_fragments = 0

    for fragment in fragments:
        if C_CELL not in fragment:
            if rows:
                if fragment:
                    if rows[-1]:
                        rows[-1][-1] = "\r".join(part for part in (rows[-1][-1], fragment) if part)
                    else:
                        rows[-1].append(fragment)
            elif fragment:
                pending_before_first_row.append(fragment)
            continue

        marked_fragments += 1
        if pending_before_first_row:
            fragment = "\r".join([*pending_before_first_row, fragment])
            pending_before_first_row.clear()
        raw_cells = fragment.split(C_CELL)
        cells = _without_final_split_cell(raw_cells)
        if cells:
            ncols = detect_column_count(raw_cells)
            chunked = chunk_cells(raw_cells, ncols)
            if len(chunked) > 1:
                rows.extend(chunked)
            else:
                rows.append(cells)

    if marked_fragments < 2:
        return None
    if not any(any(not _is_empty_cell(cell) for cell in row) for row in rows):
        return None
    return rows


def render_markdown_table(rows: list[list[str]]) -> str:
    """Render rows as a GitHub-flavoured Markdown pipe table.

    The first row is the header. Rows are padded to the widest row; cells are
    cleaned with :func:`clean_cell`.
    """
    if not rows:
        return ""
    cleaned = [[clean_cell(c) for c in row] for row in rows]
    ncols = max(len(r) for r in cleaned)
    cleaned = [r + [""] * (ncols - len(r)) for r in cleaned]
    keep_cols = [
        idx
        for idx in range(ncols)
        if any(row[idx].strip() for row in cleaned)
    ]
    if keep_cols:
        cleaned = [[row[idx] for idx in keep_cols] for row in cleaned]
        ncols = len(keep_cols)
    if ncols > _MAX_COLS:
        lines = []
        for row in cleaned:
            trimmed = list(row)
            while trimmed and not trimmed[-1].strip():
                trimmed.pop()
            if trimmed:
                lines.append("\t".join(trimmed))
        return "\n".join(lines)
    header = cleaned[0]
    body = cleaned[1:]
    sep = "| " + " | ".join("---" for _ in range(ncols)) + " |"
    lines = ["| " + " | ".join(header) + " |", sep]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)
