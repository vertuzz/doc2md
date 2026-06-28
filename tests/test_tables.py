"""Tests for table grouping, the column-count heuristic and Markdown rendering."""
from __future__ import annotations

from doc2md import tables


def test_clean_cell_escapes_pipe_and_collapses_controls():
    assert tables.clean_cell("a|b") == r"a\|b"
    assert tables.clean_cell("a\x0bb") == "a b"
    assert tables.clean_cell("a\rb") == "a b"
    assert tables.clean_cell("  trim  ") == "trim"
    # Field instructions are dropped, results kept.
    assert tables.clean_cell("\x13HYPERLINK\x14visible\x15") == "visible"


def test_detect_column_count_sample_shape():
    # Mirrors file-sample_100kB.doc: 31 cells (leading + 30), rows of 5 with
    # numeric first cells 1..5 and a trailing empty cell.
    cells = ["", "Lorem", "Lorem", "Lorem", "", "1", "In eleifend", "Lorem", "", "",
             "2", "Cras", "Ipsum", "", "", "3", "Aliquam", "Lorem", "", "",
             "4", "Fusce", "Lorem", "", "", "5", "Etiam", "Ipsum", "", "", ""]
    assert tables.detect_column_count(cells) == 4


def test_detect_column_count_row_terminator_shape():
    cells = ["Heading1", "Heading2", "", "A simple table", "Ooo", "", ""]
    assert tables.detect_column_count(cells) == 2
    assert tables.chunk_cells(cells, 2) == [["Heading1", "Heading2"], ["A simple table", "Ooo"]]


def test_detect_column_count_prefixed_row_terminator_shape():
    cells = [
        "Region", "", "", "",
        "Argentina", "www.example/ar", "Guatemala", "www.example/gt", "",
        "Australia", "www.example/au", "Jamaica", "www.example/jm", "", "",
    ]

    assert tables.detect_column_count(cells) == 4
    assert tables.chunk_cells(cells, 4) == [
        ["Region"],
        ["Argentina", "www.example/ar", "Guatemala", "www.example/gt"],
        ["Australia", "www.example/au", "Jamaica", "www.example/jm"],
    ]


def test_detect_column_count_financial_matrix_shape():
    cells = [
        "COLGATE", "", "", "",
        "", "2006", "2005", "2004",
        "Net Sales", "144%", "134%", "125%",
        "Gross Profit", "160%", "147%", "136%",
        "",
    ]

    assert tables.detect_column_count(cells) == 4


def test_detect_column_count_falls_back_to_single_row():
    cells = ["just", "some", "text", "without", "repeating", "labels", "here"]
    # No label-driven divisor: fall back to a single row.
    assert tables.detect_column_count(cells) == len(cells)


def test_chunk_cells_trims_trailing_empty():
    cells = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", ""]
    rows = tables.chunk_cells(cells, 5)
    assert rows == [["a", "b", "c", "d", "e"], ["f", "g", "h", "i", "j"]]


def test_chunk_segmented_cells_keeps_paragraph_rows():
    rows = tables.chunk_segmented_cells([
        "Name\x07Value\x07",
        "Assets\x07100\x07",
        "Liabilities\x0750\x07",
    ])

    assert rows == [["Name", "Value"], ["Assets", "100"], ["Liabilities", "50"]]


def test_chunk_segmented_cells_appends_cell_internal_paragraphs():
    rows = tables.chunk_segmented_cells([
        "Intro",
        "Question\x07Answer\x07",
        "continued answer",
        "Next\x07Done\x07",
    ])

    assert rows == [["Intro\rQuestion", "Answer\rcontinued answer"], ["Next", "Done"]]


def test_render_markdown_table_basic():
    rows = [["Name", "Value"], ["a", "1"], ["b", "2"]]
    out = tables.render_markdown_table(rows)
    lines = out.splitlines()
    assert lines[0] == "| Name | Value |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| a | 1 |"
    assert lines[3] == "| b | 2 |"


def test_render_markdown_table_pads_ragged_rows():
    rows = [["h1", "h2"], ["only-one"]]
    out = tables.render_markdown_table(rows)
    assert "| only-one |  |" in out


def test_render_markdown_table_escapes_pipes_in_cells():
    rows = [["h"], ["a|b"]]
    out = tables.render_markdown_table(rows)
    assert r"| a\|b |" in out


def test_render_markdown_table_empty():
    assert tables.render_markdown_table([]) == ""


def test_render_markdown_table_falls_back_for_overwide_layout_grid():
    rows = [["h"] + [f"c{i}" for i in range(25)]]
    out = tables.render_markdown_table(rows)
    assert not out.startswith("|")
    assert "\t" in out
