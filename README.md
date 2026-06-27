# doc2markdown

`doc2markdown` is a small, zero-runtime-dependency converter for legacy Microsoft Word
97-2003 `.doc` files. It reads the OLE2/Compound File Binary container directly and
extracts the main document text as Markdown, including a best-effort rendering of
tables, headings, lists, and basic bold/italic formatting.

It is designed for scripting, batch conversion, and dependency use in Python projects.

## Install and Run

Run directly from a GitHub repository with `uvx`:

```bash
uvx --from git+https://github.com/<owner>/<repo>.git doc2markdown input.doc -o output.md
```

Install as a persistent command-line tool:

```bash
uv tool install --from git+https://github.com/<owner>/<repo>.git doc2markdown
doc2markdown input.doc -o output.md
```

Use it as a project dependency:

```bash
uv add "doc2markdown @ git+https://github.com/<owner>/<repo>.git"
```

Then call it from Python:

```python
from doc2markdown import convert_path

markdown = convert_path("input.doc")
```

The old command name is also kept as a compatibility alias:

```bash
doctotext input.doc -o output.md
```

## CLI

```bash
doc2markdown INPUT.doc
doc2markdown INPUT.doc -o output.md
doc2markdown INPUT.doc --plain
```

By default the command writes UTF-8 Markdown to stdout. With `-o/--output`, output is
written with LF line endings on Windows, macOS, and Linux. `--plain` disables Markdown
inline markup for headings and emphasis, while table output remains Markdown-friendly.

## Python API

```python
from doc2markdown import convert_bytes, convert_path

markdown = convert_path("legacy.doc")
markdown_from_bytes = convert_bytes(doc_bytes)
```

Both helpers accept `plain=True` and an optional warning callback:

```python
markdown = convert_path("legacy.doc", warn=print)
```

## Public Sample Documents

Binary `.doc` files are intentionally ignored by Git. To run local regression checks
against public real-world files without committing them, download samples into the
ignored `samples/` folder:

```bash
uv run python scripts/download_public_samples.py
uv run python scripts/convert_samples.py samples/financial markdown-output/financial-downloads
```

The downloader stores only public source URLs in this repository; the downloaded Word
documents and generated Markdown outputs stay local.

## Development

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv build
```

The test suite is self-contained and does not require committed `.doc` fixtures.
Synthetic OLE2/WordDocument fixtures are generated in memory so the project can be
tested after a clean clone on Windows, macOS, and Linux.

## Scope and Limitations

This project is a lightweight parser, not a full Word layout engine. It targets legacy
binary `.doc` files, not `.docx`. It should preserve useful text and many tables, but
complex layout tables, embedded objects, tracked changes, unusual encodings, and
document features outside the main story may still need a heavier fallback such as
LibreOffice for pixel-perfect or production-archival conversion.

## License

MIT. See [LICENSE](LICENSE).
