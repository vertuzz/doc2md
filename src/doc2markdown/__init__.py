"""Lightweight Word 97-2003 ``.doc`` to Markdown conversion."""

from __future__ import annotations

from .cli import convert, convert_bytes, convert_path, main, render

__all__ = [
    "convert",
    "convert_bytes",
    "convert_path",
    "main",
    "render",
]

__version__ = "0.1.0"
