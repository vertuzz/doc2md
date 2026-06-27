"""Convert local .doc samples to Markdown files."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

try:
    import doc2markdown
except ModuleNotFoundError:  # pragma: no cover - convenience for direct script use
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    import doc2markdown


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--plain", action="store_true", help="disable Markdown inline markup")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    docs = sorted(args.input_dir.rglob("*.doc"))
    if not docs:
        print(f"no .doc files found under {args.input_dir}", file=sys.stderr)
        return 1

    failures = 0
    for doc_path in docs:
        rel = doc_path.relative_to(args.input_dir)
        out_path = (args.output_dir / rel).with_suffix(rel.suffix + ".md")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        warnings: list[str] = []
        try:
            markdown = doc2markdown.convert_path(doc_path, plain=args.plain, warn=warnings.append)
            text = markdown + ("" if markdown.endswith("\n") else "\n")
            out_path.write_text(text, encoding="utf-8")
        except Exception as exc:  # pragma: no cover - batch script diagnostics
            print(f"fail {doc_path}: {exc}", file=sys.stderr)
            failures += 1
            continue
        suffix = f" warnings={len(warnings)}" if warnings else ""
        print(f"ok {doc_path} -> {out_path}{suffix}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
