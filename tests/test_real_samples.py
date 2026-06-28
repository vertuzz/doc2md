"""Smoke tests for optional local real-world .doc samples."""
from __future__ import annotations

from pathlib import Path

import pytest

import doc2md


SAMPLE_NAMES = [
    "scouting_council_annual_report_contents.doc",
    "dc_regs_rule_225.doc",
    "siue_annual_report_project.doc",
    "cerritos_cash_flows_notes.doc",
]


def _local_sample_paths() -> list[Path]:
    repo = Path(__file__).resolve().parents[1]
    roots = [
        repo / "samples" / "financial",
        repo / "downloaded-docs" / "financial",
    ]
    paths: list[Path] = []
    for name in SAMPLE_NAMES:
        for root in roots:
            path = root / name
            if path.exists() and path.stat().st_size > 0:
                paths.append(path)
                break
    return paths


def test_local_real_doc_samples_smoke():
    samples = _local_sample_paths()
    if not samples:
        pytest.skip("no local public .doc samples; run scripts/download_public_samples.py")

    for path in samples:
        warnings: list[str] = []
        text = doc2md.convert_path(path, plain=True, warn=warnings.append)

        assert text.strip(), f"{path.name} converted to empty text"
