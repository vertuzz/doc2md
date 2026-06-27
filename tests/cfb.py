"""Minimal Compound File Binary (CFB) builder for unit tests.

Constructs a tiny but valid OLE2 container from a ``{name: bytes}`` mapping so the
OLE2 reader and the doc reader can be exercised without external fixtures. The
layout is deliberately simple: one FAT sector, one directory sector, an optional
mini-FAT sector for small streams, the root mini-stream, and regular FAT-backed
sectors for large streams. Up to three streams fit in a single 512-byte
directory page (root + 3 streams = 4 entries).
"""
from __future__ import annotations

import struct

SECTOR = 512
MINI = 64
ENDOFCHAIN = -2
FREESECT = -1
FATSECT = -3

SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _make_entry(name, type_, left, right, child, start, size):
    e = bytearray(128)
    nb = name.encode("utf-16le") + b"\x00\x00"
    e[0 : len(nb)] = nb
    struct.pack_into("<H", e, 64, len(nb))  # name length incl. null terminator
    e[66] = type_
    e[67] = 0  # color (black)
    struct.pack_into("<i", e, 68, left)
    struct.pack_into("<i", e, 72, right)
    struct.pack_into("<i", e, 76, child)
    struct.pack_into("<i", e, 116, start)
    struct.pack_into("<q", e, 120, size)
    return bytes(e)


def build_cfb(streams: dict[str, bytes], mini_cutoff: int = 4096) -> bytes:
    """Return bytes of a CFB container holding the supplied streams."""
    names = list(streams.keys())
    mini_names = [n for n in names if 0 < len(streams[n]) < mini_cutoff]
    big_names = [n for n in names if len(streams[n]) >= mini_cutoff]

    # Mini-stream buffer and per-stream starting mini sector.
    mini_buf = bytearray()
    mini_start: dict[str, int] = {}
    for n in mini_names:
        mini_start[n] = len(mini_buf) // MINI
        mini_buf.extend(streams[n])
        mini_buf.extend(b"\x00" * (-len(mini_buf) % MINI))

    # Mini-FAT chains.
    minifat: list[int] = []
    for n in mini_names:
        nsec = (len(streams[n]) + MINI - 1) // MINI
        base = len(minifat)
        for k in range(nsec):
            minifat.append(base + k + 1 if k < nsec - 1 else ENDOFCHAIN)

    root_data = bytes(mini_buf)
    root_size = len(root_data)

    # Sector allocation.
    fat_idx = 0
    dir_idx = 1
    nxt = 2
    minifat_idx = -1
    if mini_names:
        minifat_idx = nxt
        nxt += 1
    root_idx = -1
    if root_size > 0:
        root_idx = nxt
        nxt += (root_size + SECTOR - 1) // SECTOR
    big_idx: dict[str, int] = {}
    for n in big_names:
        big_idx[n] = nxt
        nxt += (len(streams[n]) + SECTOR - 1) // SECTOR
    total = nxt

    fat = [FREESECT] * total
    fat[fat_idx] = FATSECT
    fat[dir_idx] = ENDOFCHAIN
    if minifat_idx >= 0:
        fat[minifat_idx] = ENDOFCHAIN
    if root_idx >= 0:
        nsec = (root_size + SECTOR - 1) // SECTOR
        for k in range(nsec):
            fat[root_idx + k] = root_idx + k + 1 if k < nsec - 1 else ENDOFCHAIN
    for n in big_names:
        start = big_idx[n]
        nsec = (len(streams[n]) + SECTOR - 1) // SECTOR
        for k in range(nsec):
            fat[start + k] = start + k + 1 if k < nsec - 1 else ENDOFCHAIN

    sectors = [bytearray(SECTOR) for _ in range(total)]
    # FAT sector.
    fatb = bytearray(struct.pack("<%di" % len(fat), *fat))
    fatb.extend(b"\x00" * (SECTOR - len(fatb)))
    sectors[fat_idx] = fatb
    # Mini-FAT sector.
    if minifat_idx >= 0:
        mfb = bytearray(struct.pack("<%di" % len(minifat), *minifat))
        mfb.extend(b"\x00" * (SECTOR - len(mfb)))
        sectors[minifat_idx] = mfb
    # Root / mini-stream sector(s).
    if root_idx >= 0:
        rb = bytearray(root_data)
        rb.extend(b"\x00" * (-len(rb) % SECTOR))
        for k in range((root_size + SECTOR - 1) // SECTOR):
            sectors[root_idx + k] = rb[k * SECTOR : k * SECTOR + SECTOR]
    # Big stream sector(s).
    for n in big_names:
        data = streams[n]
        start = big_idx[n]
        nsec = (len(data) + SECTOR - 1) // SECTOR
        padded = data + b"\x00" * (-len(data) % SECTOR)
        for k in range(nsec):
            sectors[start + k] = bytearray(padded[k * SECTOR : k * SECTOR + SECTOR])

    # Directory sector.
    dirb = bytearray(SECTOR)
    child = 1 if names else -1
    dirb[0:128] = _make_entry("Root Entry", 5, -1, -1, child, root_idx, root_size)
    for i, n in enumerate(names):
        idx = 1 + i
        right = idx + 1 if idx + 1 <= len(names) else -1
        if n in mini_names:
            start = mini_start[n]
        elif n in big_names:
            start = big_idx[n]
        else:
            start = ENDOFCHAIN  # empty stream
        dirb[idx * 128 : idx * 128 + 128] = _make_entry(n, 2, -1, right, -1, start, len(streams[n]))
    sectors[dir_idx] = dirb

    # Header.
    header = bytearray(512)
    header[0:8] = SIGNATURE
    struct.pack_into("<H", header, 30, 9)   # sectorShift -> 512
    struct.pack_into("<H", header, 32, 6)  # miniSectorShift -> 64
    struct.pack_into("<I", header, 56, mini_cutoff)
    struct.pack_into("<i", header, 48, dir_idx)        # first directory sector
    struct.pack_into("<i", header, 60, minifat_idx if minifat_idx >= 0 else ENDOFCHAIN)
    struct.pack_into("<I", header, 64, 1 if mini_names else 0)  # num miniFAT sectors
    struct.pack_into("<i", header, 68, ENDOFCHAIN)      # first DIFAT sector (none)
    struct.pack_into("<I", header, 72, 0)               # num DIFAT sectors
    # DIFAT in header: first entry points to the FAT sector.
    struct.pack_into("<i", header, 76, fat_idx)
    for i in range(1, 109):
        struct.pack_into("<i", header, 76 + i * 4, FREESECT)

    return bytes(header) + b"".join(bytes(s) for s in sectors)
