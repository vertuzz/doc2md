"""Tests for the OLE2 / CFB reader."""
from __future__ import annotations

import pytest

from doc2markdown.ole2 import OLE2Reader, OLEError

from cfb import build_cfb


def test_rejects_non_cfb():
    with pytest.raises(OLEError):
        OLE2Reader(b"not a compound file at all" + b"\x00" * 600)


def test_synthetic_mini_and_big_streams():
    mini_content = b"mini-stream-data" * 2
    big_content = b"BIG" * 2048
    cfb = build_cfb({"Mini": mini_content, "Big": big_content}, mini_cutoff=4096)

    ole = OLE2Reader(cfb)

    assert ole.sector_size == 512
    assert ole.root is not None and ole.root.is_root()
    assert ole.read_stream("Mini") == mini_content
    assert ole.read_stream("Big") == big_content
    with pytest.raises(OLEError):
        ole.read_stream("Nope")


def test_synthetic_empty_stream():
    cfb = build_cfb({"Empty": b"", "Big": b"x" * 4096})

    ole = OLE2Reader(cfb)

    assert ole.read_stream("Empty") == b""
    assert ole.read_stream("Big") == b"x" * 4096


def test_synthetic_multisector_big_stream():
    payload = bytes((i * 7) % 256 for i in range(4096 * 2))
    cfb = build_cfb({"Data": payload})

    ole = OLE2Reader(cfb)

    assert ole.read_stream("Data") == payload
