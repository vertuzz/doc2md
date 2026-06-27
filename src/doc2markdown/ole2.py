"""Minimal OLE2 / Compound File Binary (CFB) reader using only the stdlib.

Parses the container used by Word 97-2003 ``.doc`` files: header, DIFAT, FAT,
MiniFAT, directory tree and stream reading (both regular FAT-backed streams and
small mini-stream backed streams). No third-party dependencies.
"""
from __future__ import annotations

import struct

# CFB signature.
SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# Sector-chain sentinels (stored as signed int32 in the FAT/DIFAT arrays).
ENDOFCHAIN = -2
FREESECT = -1
FATSECT = -3
DIFSECT = -4

# Directory entry object types.
OBJ_UNKNOWN = 0
OBJ_STORAGE = 1
OBJ_STREAM = 2
OBJ_ROOT = 5


class OLEError(Exception):
    """Raised when the CFB container cannot be parsed."""


class DirEntry:
    """A single directory entry (storage, stream or root)."""

    __slots__ = (
        "name",
        "type",
        "color",
        "left",
        "right",
        "child",
        "start",
        "size",
        "index",
    )

    def __init__(self, name, type_, color, left, right, child, start, size, index):
        self.name = name
        self.type = type_
        self.color = color
        self.left = left
        self.right = right
        self.child = child
        self.start = start
        self.size = size
        self.index = index

    def is_stream(self) -> bool:
        return self.type == OBJ_STREAM

    def is_storage(self) -> bool:
        return self.type == OBJ_STORAGE

    def is_root(self) -> bool:
        return self.type == OBJ_ROOT

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        kind = {OBJ_STREAM: "stream", OBJ_STORAGE: "storage", OBJ_ROOT: "root"}.get(
            self.type, f"type{self.type}"
        )
        return f"<DirEntry {self.name!r} {kind} start={self.start} size={self.size}>"


class OLE2Reader:
    """Read streams out of a CFB (OLE2) compound file held in memory."""

    def __init__(self, data: bytes):
        if not isinstance(data, (bytes, bytearray)):
            raise OLEError("data must be bytes")
        self.data = bytes(data)
        try:
            self._parse_header()
            self._build_fat()
            self._build_directory()
            self._build_ministream()
            self._build_name_map()
        except struct.error as exc:
            raise OLEError(f"malformed CFB/OLE2 file ({exc})") from exc

    # ------------------------------------------------------------------ header
    def _parse_header(self) -> None:
        d = self.data
        if len(d) < 512 or d[:8] != SIGNATURE:
            raise OLEError("not a CFB/OLE2 file (bad signature)")
        self.sector_shift = struct.unpack_from("<H", d, 30)[0]
        self.mini_sector_shift = struct.unpack_from("<H", d, 32)[0]
        if self.sector_shift not in (9, 12) or self.mini_sector_shift != 6:
            raise OLEError(
                f"unsupported sector shifts: {self.sector_shift}/{self.mini_sector_shift}"
            )
        self.sector_size = 1 << self.sector_shift
        self.mini_sector_size = 1 << self.mini_sector_shift
        self.num_dir_sectors = struct.unpack_from("<I", d, 40)[0]
        self.num_fat_sectors = struct.unpack_from("<I", d, 44)[0]
        self.first_dir_sector = struct.unpack_from("<i", d, 48)[0]
        self.mini_cutoff = struct.unpack_from("<I", d, 56)[0] or 4096
        self.first_minifat_sector = struct.unpack_from("<i", d, 60)[0]
        self.num_minifat = struct.unpack_from("<I", d, 64)[0]
        self.first_difat_sector = struct.unpack_from("<i", d, 68)[0]
        self.num_difat = struct.unpack_from("<I", d, 72)[0]

    def _sector_offset(self, sector: int) -> int:
        return (sector + 1) * self.sector_size

    # --------------------------------------------------------------------- FAT
    def _build_fat(self) -> None:
        # The first 109 DIFAT entries live in the header (signed int32; negatives
        # are sentinels and are skipped).
        difat = list(struct.unpack_from("<109i", self.data, 76))
        # Follow the DIFAT chain for any additional FAT-sector pointers.
        per = self.sector_size // 4
        s = self.first_difat_sector
        guard = 0
        while s is not None and s >= 0 and guard < self.num_difat + 1:
            guard += 1
            off = self._sector_offset(s)
            vals = struct.unpack_from(f"<{per}i", self.data, off)
            difat.extend(vals[:-1])
            nxt = vals[-1]
            s = None if nxt < 0 else nxt

        self.fat: list[int] = []
        for s in difat:
            if s < 0:
                continue
            off = self._sector_offset(s)
            if off + self.sector_size > len(self.data):
                # Truncated FAT sector; read what is available.
                chunk = self.data[off:]
                count = len(chunk) // 4
                self.fat.extend(struct.unpack(f"<{count}i", chunk[: count * 4]))
                continue
            self.fat.extend(struct.unpack_from(f"<{per}i", self.data, off))

    def _build_minifat(self) -> None:
        self.minifat: list[int] = []
        s = self.first_minifat_sector
        per = self.sector_size // 4
        seen: set[int] = set()
        while s is not None and s >= 0 and s not in seen:
            seen.add(s)
            if s >= len(self.fat):
                break
            off = self._sector_offset(s)
            if off + self.sector_size <= len(self.data):
                self.minifat.extend(struct.unpack_from(f"<{per}i", self.data, off))
            s = self.fat[s]
            if s is not None and s < 0:
                break

    # --------------------------------------------------------------- directory
    def _build_directory(self) -> None:
        self.entries: list[DirEntry] = []
        s = self.first_dir_sector
        seen: set[int] = set()
        per = self.sector_size // 128
        while s is not None and s >= 0 and s not in seen:
            seen.add(s)
            if s >= len(self.fat):
                break
            off = self._sector_offset(s)
            for i in range(per):
                base = off + i * 128
                chunk = self.data[base : base + 128]
                if len(chunk) < 128:
                    break
                self.entries.append(self._parse_entry(chunk, len(self.entries)))
            s = self.fat[s]
            if s is not None and s < 0:
                break

    @staticmethod
    def _parse_entry(chunk: bytes, index: int) -> DirEntry:
        name_len = struct.unpack_from("<H", chunk, 64)[0]
        if name_len >= 2:
            name_len = min(name_len, 64)
            name = chunk[: name_len - 2].decode("utf-16le", "replace")
        else:
            name = ""
        type_ = chunk[66]
        color = chunk[67]
        left = struct.unpack_from("<i", chunk, 68)[0]
        right = struct.unpack_from("<i", chunk, 72)[0]
        child = struct.unpack_from("<i", chunk, 76)[0]
        start = struct.unpack_from("<i", chunk, 116)[0]
        size = struct.unpack_from("<q", chunk, 120)[0]
        return DirEntry(name, type_, color, left, right, child, start, size, index)

    def _walk_rb(self, node: int, out: list[DirEntry], seen: set[int]) -> None:
        while node is not None and node >= 0 and node < len(self.entries) and node not in seen:
            seen.add(node)
            entry = self.entries[node]
            out.append(entry)
            self._walk_rb(entry.left, out, seen)
            node = entry.right

    # ------------------------------------------------------------- mini-stream
    def _build_ministream(self) -> None:
        root = next((e for e in self.entries if e.is_root()), None)
        self.root = root
        if root is None:
            self.mini_stream = b""
            return
        # The root entry's stream IS the mini-stream and is always FAT-backed.
        self.mini_stream = self._read_fat_chain(root.start, root.size)
        self._build_minifat()

    def _build_name_map(self) -> None:
        self.name_map: dict[str, DirEntry] = {}
        if self.root is None:
            return
        top: list[DirEntry] = []
        self._walk_rb(self.root.child, top, set())
        for entry in top:
            # Last write wins; the streams we care about are unique at the top level.
            self.name_map[entry.name] = entry

    # ------------------------------------------------------------- stream I/O
    def _read_fat_chain(self, start: int, size: int | None) -> bytes:
        out = bytearray()
        s = start
        seen: set[int] = set()
        while s is not None and s >= 0 and s not in seen:
            seen.add(s)
            if s >= len(self.fat):
                break
            off = self._sector_offset(s)
            out += self.data[off : off + self.sector_size]
            nxt = self.fat[s]
            s = None if nxt < 0 else nxt
            if size is not None and len(out) >= size:
                break
        if size is not None:
            return bytes(out[:size])
        return bytes(out)

    def _read_mini_chain(self, start: int, size: int) -> bytes:
        out = bytearray()
        s = start
        seen: set[int] = set()
        while s is not None and s >= 0 and s not in seen:
            seen.add(s)
            if s >= len(self.minifat):
                break
            off = s * self.mini_sector_size
            out += self.mini_stream[off : off + self.mini_sector_size]
            nxt = self.minifat[s]
            s = None if nxt < 0 else nxt
            if len(out) >= size:
                break
        return bytes(out[:size])

    def read_entry(self, entry: DirEntry) -> bytes:
        if entry.size == 0 or entry.start < 0:
            return b""
        if entry.is_root():
            return self._read_fat_chain(entry.start, entry.size)
        if entry.size < self.mini_cutoff:
            return self._read_mini_chain(entry.start, entry.size)
        return self._read_fat_chain(entry.start, entry.size)

    def read_stream(self, name: str) -> bytes:
        entry = self.name_map.get(name)
        if entry is None:
            raise OLEError(f"stream not found: {name!r}")
        return self.read_entry(entry)

    def has_stream(self, name: str) -> bool:
        return name in self.name_map and self.name_map[name].size > 0
