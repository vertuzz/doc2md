"""Paragraph/character property extraction for Word 97-2003 ``.doc`` files.

Resolves the paragraph properties (PAP) for a character position by walking the
paragraph bin table (PlcBtePapx) into the PAPX formatted-disk pages stored in the
WordDocument stream and decoding the grpprl of single property modifiers (sprms).
Only the properties needed for table detection and light Markdown enrichment are
extracted. Uses only the standard library.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

# ----------------------------------------------------------------- sprm format
# sprm (16 bits): ispmd(0-8) | fSpec(9) | sgc(10-12) | spra(13-15)
SGC_PARA = 1
SGC_CHAR = 2

# Operand size indexed by the 3-bit spra field.
SPRA_SIZE = {0: 1, 1: 1, 2: 2, 3: 4, 4: 2, 5: 2, 7: 3}  # 6 == variable length


def decode_sprms(grpprl: bytes) -> dict[int, bytes]:
    """Decode a grpprl into ``{sprm_code: operand_bytes}``.

    Unknown or truncated sprms stop the scan; the function never raises so that a
    malformed tail does not lose the earlier, valid properties.
    """
    out: dict[int, bytes] = {}
    i = 0
    n = len(grpprl)
    while i + 2 <= n:
        sprm = struct.unpack_from("<H", grpprl, i)[0]
        sgc = (sprm >> 10) & 7
        spra = (sprm >> 13) & 7
        if spra == 6:
            if i + 3 > n:
                break
            op_len = 1 + grpprl[i + 2]
        else:
            op_len = SPRA_SIZE.get(spra, 1)
        op_start = i + 2
        op_end = op_start + op_len
        if op_end > n:
            break
        out[sprm] = grpprl[op_start:op_end]
        i = op_end
        # Stop if the sprm is not a plausible property modifier.
        if sgc < 1 or sgc > 5:
            break
    return out


# ----------------------------------------------------------- sprm code tables
# Paragraph property modifiers (sgc == 1).
SPRM_PISTD = 0x4600  # paragraph style istd (u16); istd 1-9 implies outline level
SPRM_PILVL = 0x260A  # list level (u8)
SPRM_PILFO = 0x460B  # list format override index (i16)
SPRM_PFINTABLE = 0x2416  # fInTable (Bool8)
SPRM_PFTTP = 0x2417  # table-terminating paragraph mark (Bool8)
SPRM_POUTLVL = 0x2640  # outline level (u8); 0x0-0x8 level, 0x9 body
SPRM_PITAP = 0x6649  # table depth (i32)
SPRM_PDTAP = 0x664A  # table depth delta (i32)

# Character property modifiers (sgc == 2).
SPRM_CFBOLD = 0x0835  # ToggleOperand
SPRM_CFITALIC = 0x0836  # ToggleOperand
SPRM_CKUL = 0x2A3E  # underline style (Kul); 0 == none


def _toggle_on(value: int) -> bool:
    """Interpret a ToggleOperand byte as the property being ON.

    0x01 turns the property on. 0x81 toggles the inherited value, which this
    lightweight parser does not resolve, so it is not treated as an explicit ON.
    0x00 and 0x80 are off.
    """
    return value == 0x01


@dataclass
class Pap:
    f_in_table: bool = False
    f_ttp: bool = False
    itap: int = 0
    ilfo: int = 0  # 0 == not in a list
    ilvl: int = 0
    istd: int = 0
    outline_level: int | None = None  # 0-8 (heading depth) or 9 (body) or None


@dataclass
class Chp:
    bold: bool = False
    italic: bool = False
    underline: bool = False


class Formatting:
    """Lazy, cached accessor for paragraph properties derived from the bin table."""

    def __init__(self, doc, warn=None):
        self.doc = doc
        self.warn = warn or (lambda m: None)
        self.word_doc = doc.word_doc
        self.table = doc.table
        self._pap_cache: dict[int, Pap] = {}
        self._fkp_cache: dict[int, list[tuple[int, int, int, bytes]]] = {}
        self._bintable = self._parse_bintable()
        self.available = self._bintable is not None
        if not self.available:
            self.warn("paragraph bin table unavailable; table/heading detection disabled")
        self._chp_runs: list[tuple[int, int, Chp]] | None = None
        self._chp_starts: list[int] = []
        try:
            self._chp_runs = self._parse_chp_runs()
            if self._chp_runs:
                self._chp_starts = [r[0] for r in self._chp_runs]
        except Exception as exc:  # pragma: no cover - defensive
            self.warn(f"character bin table parse failed ({exc}); bold/italic disabled")

    # ------------------------------------------------------------- bin table
    def _parse_bintable(self) -> tuple[list[int], list[int]] | None:
        fc, lcb = self.doc.pair(13)  # FC_PLCFBTEPAPX
        if lcb <= 0 or fc < 0 or fc + lcb > len(self.table):
            return None
        data = self.table[fc : fc + lcb]
        # PlcBtePapx: (n+1) FCs (u32) + n PNs (i32). Each PN is a page number.
        n = (lcb - 4) // 8
        if n < 1:
            return None
        a_fc = list(struct.unpack_from(f"<{n + 1}I", data, 0))
        a_pn = list(struct.unpack_from(f"<{n}i", data, 4 * (n + 1)))
        return a_fc, a_pn

    def _fkp_page(self, pn: int) -> list[tuple[int, int, int, bytes]] | None:
        """Return a list of ``(fc_start, fc_end, istd, grpprl)`` runs for a page.

        The PapxFkp pages live in the WordDocument stream at offset ``pn * 512``.
        """
        if pn in self._fkp_cache:
            return self._fkp_cache[pn]
        runs: list[tuple[int, int, int, bytes]] | None = None
        off = pn * 512
        if 0 <= off and off + 512 <= len(self.word_doc):
            page = self.word_doc[off : off + 512]
            crun = page[511]
            if 0 < crun < 45:
                rgfc = struct.unpack_from(f"<{crun + 1}I", page, 0)
                bx_base = (crun + 1) * 4
                runs = []
                for k in range(crun):
                    b_offset = page[bx_base + k * 13]
                    papx_off = 2 * b_offset
                    fc_start = rgfc[k]
                    fc_end = rgfc[k + 1]
                    istd = 0
                    grpprl = b""
                    if papx_off + 3 <= 512 and page[papx_off] != 0:
                        cb = page[papx_off]
                        istd = struct.unpack_from("<H", page, papx_off + 1)[0]
                        end = papx_off + 3 + max(0, 2 * cb - 3)
                        grpprl = page[papx_off + 3 : min(end, 512)]
                    runs.append((fc_start, fc_end, istd, grpprl))
        self._fkp_cache[pn] = runs
        return runs

    # ------------------------------------------------------------- PAP lookup
    def _run_for_fc(self, fc: int) -> tuple[int, bytes] | None:
        a_fc, a_pn = self._bintable  # type: ignore[misc]
        j = 0
        for jj in range(len(a_pn)):
            if a_fc[jj] <= fc:
                j = jj
            else:
                break
        runs = self._fkp_page(a_pn[j])
        if not runs:
            return None
        istd = 0
        grpprl = b""
        for fc_start, fc_end, r_istd, r_grpprl in runs:
            if fc_start <= fc < fc_end:
                istd = r_istd
                grpprl = r_grpprl
                break
        return istd, grpprl

    def pap_for_cp(self, cp: int) -> Pap:
        """Return the PAP that applies at ``cp`` (cached)."""
        if cp in self._pap_cache:
            return self._pap_cache[cp]
        pap = Pap()
        if self.available:
            fc = self.doc.fc_for_cp(cp)
            if fc is not None:
                res = self._run_for_fc(fc)
                if res is not None:
                    istd, grpprl = res
                    pap.istd = istd
                    sprms = decode_sprms(grpprl)
                    pap.f_in_table = bool(sprms.get(SPRM_PFINTABLE, b"\x00")[0])
                    pap.f_ttp = bool(sprms.get(SPRM_PFTTP, b"\x00")[0])
                    if SPRM_PITAP in sprms and len(sprms[SPRM_PITAP]) >= 4:
                        pap.itap = struct.unpack("<i", sprms[SPRM_PITAP])[0]
                    if SPRM_PILFO in sprms and len(sprms[SPRM_PILFO]) >= 2:
                        pap.ilfo = struct.unpack("<h", sprms[SPRM_PILFO])[0]
                    if SPRM_PILVL in sprms:
                        pap.ilvl = sprms[SPRM_PILVL][0]
                    if SPRM_POUTLVL in sprms:
                        pap.outline_level = sprms[SPRM_POUTLVL][0]
                    elif 1 <= istd <= 9:
                        pap.outline_level = istd - 1
        self._pap_cache[cp] = pap
        return pap

    # --------------------------------------------------- character properties
    def _parse_chp_runs(self) -> list[tuple[int, int, Chp]] | None:
        """Build a flat list of ``(fc_start, fc_end, Chp)`` runs from the
        character bin table (PlcBteChpx). The ChpxFkp pages also live in the
        WordDocument stream at ``pn * 512``."""
        fc, lcb = self.doc.pair(12)  # FC_PLCFBTECHPX
        if lcb <= 0 or fc < 0 or fc + lcb > len(self.table):
            return None
        data = self.table[fc : fc + lcb]
        n = (lcb - 4) // 8
        if n < 1:
            return None
        a_pn = list(struct.unpack_from(f"<{n}i", data, 4 * (n + 1)))
        runs: list[tuple[int, int, Chp]] = []
        for j in range(n):
            pn = a_pn[j]
            if pn < 0:
                continue
            off = pn * 512
            if not (0 <= off and off + 512 <= len(self.word_doc)):
                continue
            page = self.word_doc[off : off + 512]
            crun = page[511]
            if not (0 < crun < 45):
                continue
            rgfc = struct.unpack_from(f"<{crun + 1}I", page, 0)
            rgb_base = (crun + 1) * 4
            for k in range(crun):
                chpx_off = page[rgb_base + k]
                chp = Chp()
                if 0 < chpx_off < 512:
                    cb = page[chpx_off]
                    grpprl = page[chpx_off + 1 : min(chpx_off + 1 + cb, 512)]
                    sprms = decode_sprms(grpprl)
                    if SPRM_CFBOLD in sprms:
                        chp.bold = _toggle_on(sprms[SPRM_CFBOLD][0])
                    if SPRM_CFITALIC in sprms:
                        chp.italic = _toggle_on(sprms[SPRM_CFITALIC][0])
                    if SPRM_CKUL in sprms:
                        chp.underline = sprms[SPRM_CKUL][0] != 0
                runs.append((rgfc[k], rgfc[k + 1], chp))
        runs.sort()
        return runs or None

    def chp_for_cp(self, cp: int) -> Chp:
        """Return the direct character properties at ``cp`` (bold/italic/underline)."""
        if not self._chp_runs:
            return Chp()
        fc = self.doc.fc_for_cp(cp)
        if fc is None:
            return Chp()
        import bisect
        idx = bisect.bisect_right(self._chp_starts, fc) - 1
        if idx < 0:
            return Chp()
        fc_start, fc_end, chp = self._chp_runs[idx]
        if fc_start <= fc < fc_end:
            return chp
        return Chp()
