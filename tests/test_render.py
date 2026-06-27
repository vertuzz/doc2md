"""Tests for Markdown rendering edge cases."""
from __future__ import annotations

from types import SimpleNamespace

import doc2markdown


class _Pap:
    f_in_table = True
    outline_level = None
    ilfo = 0
    ilvl = 0


class _Chp:
    def __init__(self, bold=False, italic=False):
        self.bold = bold
        self.italic = italic


class _ResidualTableFmt:
    available = True

    def pap_for_cp(self, _cp):
        return _Pap()

    def chp_for_cp(self, cp):
        return _Chp(bold=4 <= cp <= 6)


def test_residual_table_paragraphs_keep_their_cp_coordinates():
    doc = SimpleNamespace(body="one\rtwo\r")

    rendered = doc2markdown.render(doc, _ResidualTableFmt(), plain=False)

    assert rendered == "one\n\n**two**"
