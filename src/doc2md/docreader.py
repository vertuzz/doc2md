"""Word 97-2003 (``.doc``) document body reader using only the stdlib.

Parses the FIB, selects the correct table stream (``0Table``/``1Table``),
extracts the piece table (CLX/Pcdt) and decodes the main document body into a
CP-indexed string. Falls back to a best-effort printable scrape when the piece
table is missing or malformed.
"""
from __future__ import annotations

import struct

from .ole2 import OLE2Reader

# -------------------------------------------------------------------- FIB bits
W_IDENT = 0xA5EC
F_FCOMPLEX = 1 << 2
F_WHICHTBLSTM = 1 << 9
F_FAREAST = 1 << 14

# FibRgFcLcb97 pair indices (each pair is fc:int32 + lcb:uint32 = 8 bytes).
FC_STSHF = 1  # 0x008
FC_PLCFBTECHPX = 12  # 0x060
FC_PLCFBTEPAPX = 13  # 0x068
FC_CLX = 33  # 0x108
FC_PLFLST = 73  # 0x248
FC_PLFLFO = 74  # 0x250

# CLX record types.
CLXT_PRC = 0x01
CLXT_PCDT = 0x02

# FcCompressed flags.
FC_COMPRESSED = 0x40000000
FC_OFFSET_MASK = 0x3FFFFFFF

# Control characters in the Word text stream.
CHAR_TAB = 0x09
CHAR_CELL = 0x07
CHAR_LINE = 0x0B
CHAR_PAGE = 0x0C
CHAR_PARA = 0x0D
CHAR_KEEP = {CHAR_TAB, CHAR_CELL, CHAR_LINE, CHAR_PAGE, CHAR_PARA, 0x0A}


def _looks_utf16le(raw: bytes, ccp_text: int) -> bool:
    """Return True when the contiguous text bytes look like UTF-16LE."""
    if len(raw) < 2 or len(raw) < min(ccp_text * 2, 16):
        return False
    sample = raw[: min(len(raw), max(64, min(ccp_text * 2, 4096)))]
    even_nuls = sum(1 for b in sample[0::2] if b == 0)
    odd_nuls = sum(1 for b in sample[1::2] if b == 0)
    return odd_nuls > len(sample) // 4 and odd_nuls >= even_nuls * 4


class DocError(Exception):
    """Raised when the document cannot be parsed."""


class DocReader:
    """Read the main body text of a Word 97-2003 ``.doc`` document."""

    def __init__(self, ole: OLE2Reader, warn=None):
        self.ole = ole
        self.warnings: list[str] = []
        self._warn = warn or (lambda m: self.warnings.append(m))

        if not ole.has_stream("WordDocument"):
            raise DocError("not a Word document: no 'WordDocument' stream")
        self.word_doc = ole.read_stream("WordDocument")

        self._parse_fib()
        self.table = self._read_table_stream()

        self.pieces: list[tuple[int, int, int, bool, bytes]] = []
        self.text = self._extract_text()
        self.body = self.text[: self.ccp_text]

    # -------------------------------------------------------------------- FIB
    def _parse_fib(self) -> None:
        wd = self.word_doc
        if len(wd) < 34:
            raise DocError("WordDocument stream too small to contain a FIB")
        self.w_ident, self.n_fib = struct.unpack_from("<HH", wd, 0)
        if self.w_ident != W_IDENT:
            raise DocError(f"unexpected FIB wIdent: 0x{self.w_ident:04X}")
        flags = struct.unpack_from("<H", wd, 0x0A)[0]
        self.f_complex = bool(flags & F_FCOMPLEX)
        self.f_far_east = bool(flags & F_FAREAST)
        self.table_name = "1Table" if (flags & F_WHICHTBLSTM) else "0Table"
        self.fc_min, self.fc_mac = struct.unpack_from("<II", wd, 0x18)

        csw = struct.unpack_from("<H", wd, 32)[0]
        off = 34 + csw * 2
        if off + 2 > len(wd):
            raise DocError("truncated FIB (csw)")
        cslw = struct.unpack_from("<H", wd, off)[0]
        off += 2
        lwg = wd[off : off + cslw * 4]
        if len(lwg) < 44:
            raise DocError("truncated FIB (cslw)")
        (self.ccp_text, self.ccp_ftn, self.ccp_hdd, self.ccp_mcr,
         self.ccp_atn, self.ccp_edn, self.ccp_txbx, self.ccp_hdr_txbx) = \
            struct.unpack_from("<8I", lwg, 12)
        self.ccp_total = (self.ccp_text + self.ccp_ftn + self.ccp_hdd + self.ccp_mcr
                          + self.ccp_atn + self.ccp_edn + self.ccp_txbx + self.ccp_hdr_txbx)
        off += cslw * 4
        if off + 2 > len(wd):
            raise DocError("truncated FIB (cbRgFcLcb)")
        cb = struct.unpack_from("<H", wd, off)[0]
        off += 2
        self.fcb = off
        self.cb = cb  # number of fc/lcb pairs available

    def pair(self, index: int) -> tuple[int, int]:
        """Return ``(fc, lcb)`` for the given FibRgFcLcb pair index."""
        if index < 0 or index >= self.cb:
            return 0, 0
        base = self.fcb + index * 8
        if base + 8 > len(self.word_doc):
            return 0, 0
        return struct.unpack_from("<iI", self.word_doc, base)

    def _read_table_stream(self) -> bytes:
        if not self.ole.has_stream(self.table_name):
            # Some documents only emit one table stream; fall back to the other.
            for alt in ("1Table", "0Table"):
                if self.ole.has_stream(alt):
                    self._warn(f"requested '{self.table_name}' missing; using '{alt}'")
                    self.table_name = alt
                    return self.ole.read_stream(alt)
            self._warn(f"table stream '{self.table_name}' not found")
            return b""
        return self.ole.read_stream(self.table_name)

    # ------------------------------------------------------------- piece table
    def _extract_text(self) -> str:
        fc, lcb = self.pair(FC_CLX)
        if lcb <= 0 or fc < 0 or fc + lcb > len(self.table):
            if not self.f_complex:
                self._warn("CLX missing/invalid; reading simple WordDocument text")
                return self._decode_simple_text()
            self._warn("CLX missing/invalid; falling back to printable scrape")
            return self._scrape()[: self.ccp_text]
        clx = self.table[fc : fc + lcb]
        plc = self._find_pcdt(clx)
        if plc is None:
            if not self.f_complex:
                self._warn("no Pcdt in CLX; reading simple WordDocument text")
                return self._decode_simple_text()
            self._warn("no Pcdt in CLX; falling back to printable scrape")
            return self._scrape()[: self.ccp_text]
        try:
            return self._decode_plcpcd(plc)
        except (struct.error, IndexError, UnicodeError) as exc:
            if not self.f_complex:
                self._warn(f"piece table decode failed ({exc}); reading simple WordDocument text")
                return self._decode_simple_text()
            self._warn(f"piece table decode failed ({exc}); falling back to scrape")
            return self._scrape()[: self.ccp_text]

    @staticmethod
    def _find_pcdt(clx: bytes) -> bytes | None:
        i = 0
        n = len(clx)
        while i < n:
            clxt = clx[i]
            if clxt == CLXT_PCDT:
                if i + 5 > n:
                    return None
                lcb = struct.unpack_from("<i", clx, i + 1)[0]
                start = i + 5
                if lcb < 0 or start + lcb > n:
                    return None
                return clx[start : start + lcb]
            if clxt == CLXT_PRC:
                if i + 2 > n:
                    return None
                ln = clx[i + 1]
                i += 2 + ln
                continue
            # Unknown clxt: stop searching.
            return None
        return None

    def _decode_plcpcd(self, plc: bytes) -> str:
        wd = self.word_doc
        # PlcPcd: (n+1) CPs (int32) + n PCDs (8 bytes each).
        if len(plc) < 12:
            raise ValueError("PlcPcd too small")
        n = (len(plc) - 4) // 12
        if n < 1:
            raise ValueError("PlcPcd has no pieces")
        cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
        pcds = plc[4 * (n + 1) : 4 * (n + 1) + 8 * n]
        if len(pcds) < 8 * n:
            raise ValueError("truncated PCD array")

        # Each piece: (cp_start, cp_end, fc_base, compressed, prm_bytes).
        out: list[str] = []
        for k in range(n):
            cp0 = cps[k]
            cp1 = cps[k + 1]
            nch = cp1 - cp0
            pcd = pcds[k * 8 : k * 8 + 8]
            fc = struct.unpack_from("<I", pcd, 2)[0]
            compressed = bool(fc & FC_COMPRESSED)
            base = fc & FC_OFFSET_MASK
            prm = pcd[6:8]
            self.pieces.append((cp0, cp1, base, compressed, prm))
            if nch <= 0:
                continue
            if compressed:
                start = base // 2
                raw = wd[start : start + nch]
                out.append(raw.decode("cp1252", "replace"))
            else:
                start = base
                raw = wd[start : start + nch * 2]
                out.append(raw.decode("utf-16le", "replace"))
        return "".join(out)

    def _decode_simple_text(self) -> str:
        """Decode a non-complex document whose text is stored contiguously."""
        if self.fc_min >= len(self.word_doc) or self.fc_mac <= self.fc_min:
            return self._scrape()[: self.ccp_text]
        raw = self.word_doc[self.fc_min : min(self.fc_mac, len(self.word_doc))]
        compressed = not _looks_utf16le(raw, self.ccp_text)
        self.pieces = [(
            0,
            self.ccp_text,
            2 * self.fc_min if compressed else self.fc_min,
            compressed,
            b"\x00\x00",
        )]
        if compressed:
            return raw[: self.ccp_text].decode("cp1252", "replace")
        return raw[: self.ccp_text * 2].decode("utf-16le", "replace")

    def fc_for_cp(self, cp: int) -> int | None:
        """Return the un-halved file character position (fc coordinate used by
        the paragraph/character bin tables) for a given character position, or
        ``None`` if it is outside every piece."""
        for cp0, cp1, base, _compressed, _prm in self.pieces:
            if cp0 <= cp < cp1:
                return base + 2 * (cp - cp0)
        return None

    # --------------------------------------------------------- fallback scrape
    def _scrape(self) -> str:
        """Best-effort extraction of printable text from the WordDocument stream."""
        wd = self.word_doc
        lines: list[str] = []
        buf = bytearray()

        def flush() -> None:
            printable = sum(
                c.isalnum() or c == " "
                for c in buf.decode("ascii", "ignore")
            )
            if len(buf) >= 4 and printable >= 3:
                lines.append(buf.decode("cp1252", "replace"))
            buf.clear()

        for b in wd:
            if 0x20 <= b <= 0x7E or b in (0x09, 0x0A, 0x0D):
                buf.append(b)
            elif 0xA0 <= b <= 0xFF:
                buf.append(b)
            else:
                flush()
                if b in (CHAR_PARA, CHAR_LINE):
                    lines.append("")
        flush()
        return "\n".join(lines)
