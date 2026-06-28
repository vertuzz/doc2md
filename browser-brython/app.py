from __future__ import annotations

import base64
import codecs
import sys
import traceback

from browser import document, window


GITHUB_SRC = "https://cdn.jsdelivr.net/gh/vertuzz/doc2md@main/src"
COMPAT_SRC = "./pycompat"
LEGACY_DOC_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


state = {
    "data": None,
    "filename": "",
    "markdown": "",
}


def el(name: str):
    return document[name]


sys.path.insert(0, COMPAT_SRC)
sys.path.insert(0, GITHUB_SRC)

# Brython exposes some codecs BOM constants in a way that is not accepted by
# bytes.startswith(...). Normalise them before importing doc2md.fallback.
codecs.BOM_UTF8 = b"\xef\xbb\xbf"
codecs.BOM_UTF16_LE = b"\xff\xfe"
codecs.BOM_UTF16_BE = b"\xfe\xff"


def set_status(message: str, error: bool = False) -> None:
    status = el("status")
    status.textContent = message
    if error:
        status.classList.add("error")
    else:
        status.classList.remove("error")


def set_warnings(items: list[str]) -> None:
    box = el("warnings")
    warnings = el("warning-list")
    warnings.clear()
    if not items:
        box.classList.remove("visible")
        return
    for item in items:
        li = document.createElement("li")
        li.textContent = item
        warnings <= li
    box.classList.add("visible")


def update_buttons() -> None:
    has_output = bool(state["markdown"])
    el("copy-button").disabled = not has_output
    el("download-button").disabled = not has_output


def bytes_startswith(data: bytes, prefix: bytes) -> bool:
    return data[: len(prefix)] == prefix


def bytes_startswith_any(data: bytes, prefixes: tuple[bytes, ...]) -> bool:
    return any(bytes_startswith(data, prefix) for prefix in prefixes)


def byte_value(data: bytes, index: int) -> int:
    value = data[index]
    return ord(value) if isinstance(value, str) else value


def strip_leading_bom_and_space(data: bytes) -> bytes:
    for bom in (codecs.BOM_UTF8, codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
        if bytes_startswith(data, bom):
            data = data[len(bom) :]
            break
    pos = 0
    whitespace = {9, 10, 11, 12, 13, 32}
    while pos < len(data) and byte_value(data, pos) in whitespace:
        pos += 1
    return data[pos:]


try:
    import doc2md.cli as doc2md_cli
    import doc2md.fallback as doc2md_fallback

    def convert_alternate_bytes_browser(data: bytes, plain: bool = False, warn=None) -> str | None:
        warn = warn or (lambda _message: None)
        if not data:
            warn("empty input; returning empty output")
            return ""

        stripped = strip_leading_bom_and_space(data)
        lowered = stripped[:128].decode("latin1", "ignore").lower()

        if bytes_startswith_any(data, doc2md_fallback.ZIP_SIGNATURES):
            return doc2md_fallback._convert_ooxml_word(data, plain=plain, warn=warn)

        if lowered.startswith(tuple(prefix.decode("ascii") for prefix in doc2md_fallback.HTML_PREFIXES)):
            if "<html" in lowered:
                warn("input is HTML, not legacy OLE2 .doc; using HTML text fallback")
                return doc2md_fallback._convert_html(data)

        if lowered.startswith("{\\rtf"):
            warn("input is RTF, not legacy OLE2 .doc; using RTF text fallback")
            return doc2md_fallback._convert_rtf(data)

        return None

    doc2md_cli.convert_alternate_bytes = convert_alternate_bytes_browser
    convert_bytes = doc2md_cli.convert_bytes
except Exception:
    convert_bytes = None
    set_status("Python import failed. See the browser console for details.", error=True)
    window.console.error(traceback.format_exc())
else:
    set_status("Ready.")


def markdown_name(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return f"{stem or 'document'}.md"


def convert_current() -> None:
    if convert_bytes is None:
        return
    data = state["data"]
    if data is None:
        return

    warnings: list[str] = []

    def warn(message: str) -> None:
        warnings.append(message)

    try:
        plain = bool(el("plain-toggle").checked)
        set_status(f"Converting {state['filename']}...")
        markdown = convert_bytes(data, plain=plain, warn=warn)
    except Exception:
        state["markdown"] = ""
        el("output").value = ""
        set_warnings(warnings)
        set_status("Conversion failed. See the browser console for details.", error=True)
        window.console.error(traceback.format_exc())
        update_buttons()
        return

    state["markdown"] = markdown
    el("output").value = markdown
    el("filename").textContent = state["filename"]
    set_warnings(warnings)
    set_status(f"Converted {state['filename']} ({len(data):,} bytes).")
    update_buttons()


def read_blob(blob, filename: str) -> None:
    reader = window.FileReader.new()

    def on_load(event) -> None:
        try:
            result = str(event.target.result)
            _, payload = result.split(",", 1)
            decoded = base64.b64decode(payload)
            if isinstance(decoded, str):
                decoded = decoded.encode("latin1")
            if not is_legacy_doc(filename, decoded):
                reject_unsupported_file(filename)
                return
            state["data"] = decoded
            state["filename"] = filename
            convert_current()
        except Exception:
            set_status("Could not read the selected file.", error=True)
            window.console.error(traceback.format_exc())

    def on_error(_event) -> None:
        set_status("Could not read the selected file.", error=True)

    reader.addEventListener("load", on_load)
    reader.addEventListener("error", on_error)
    set_status(f"Reading {filename}...")
    reader.readAsDataURL(blob)


def first_file(files):
    if files is None or files.length == 0:
        return None
    try:
        return files.item(0)
    except Exception:
        return files[0]


def is_legacy_doc(filename: str, data: bytes) -> bool:
    return filename.lower().endswith(".doc") and bytes_startswith(data, LEGACY_DOC_SIGNATURE)


def reject_unsupported_file(filename: str) -> None:
    state["data"] = None
    state["filename"] = ""
    state["markdown"] = ""
    el("file-input").value = ""
    el("filename").textContent = "No legacy .doc loaded"
    el("output").value = ""
    set_warnings([])
    set_status(
        f"{filename} was not converted. This page only accepts legacy Word 97-2003 binary .doc files.",
        error=True,
    )
    update_buttons()


def handle_file(file) -> None:
    if file is None:
        return
    read_blob(file, str(file.name or "document.doc"))


def on_file_change(event) -> None:
    handle_file(first_file(event.target.files))


def on_drag_over(event) -> None:
    event.preventDefault()
    el("dropzone").classList.add("is-dragging")


def on_drag_leave(event) -> None:
    event.preventDefault()
    el("dropzone").classList.remove("is-dragging")


def on_drop(event) -> None:
    event.preventDefault()
    el("dropzone").classList.remove("is-dragging")
    handle_file(first_file(event.dataTransfer.files))


def load_sample_bytes(payload: str) -> None:
    try:
        decoded = base64.b64decode(payload.strip())
        if isinstance(decoded, str):
            decoded = decoded.encode("latin1")
        state["data"] = decoded
        state["filename"] = "sample.doc"
        convert_current()
    except Exception:
        set_status("Could not decode sample.doc.", error=True)
        window.console.error(traceback.format_exc())


def request_sample(urls: list[str], index: int = 0) -> None:
    request = window.XMLHttpRequest.new()
    is_encoded_sample = urls[index].endswith(".b64")

    def on_load(_event) -> None:
        if request.status in (200, 0):
            if is_encoded_sample:
                load_sample_bytes(str(request.responseText))
            else:
                read_blob(request.response, "sample.doc")
        elif index + 1 < len(urls):
            request_sample(urls, index + 1)
        else:
            set_status(f"Could not load sample.doc (HTTP {request.status}).", error=True)

    def on_error(_event) -> None:
        if index + 1 < len(urls):
            request_sample(urls, index + 1)
        else:
            set_status("Could not load sample.doc.", error=True)

    request.addEventListener("load", on_load)
    request.addEventListener("error", on_error)
    request.open("GET", urls[index], True)
    request.responseType = "text" if is_encoded_sample else "blob"
    request.send()


def load_sample(_event) -> None:
    set_status("Loading sample.doc...")
    request_sample(["./sample.doc.b64", "../sample.doc"])


def copy_output(_event) -> None:
    if not state["markdown"]:
        return
    window.navigator.clipboard.writeText(state["markdown"])
    set_status("Copied Markdown.")


def download_output(_event) -> None:
    if not state["markdown"]:
        return
    blob = window.Blob.new([state["markdown"]], {"type": "text/markdown;charset=utf-8"})
    url = window.URL.createObjectURL(blob)
    link = document.createElement("a")
    link.href = url
    link.download = markdown_name(state["filename"])
    document.body <= link
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)


def clear_output(_event) -> None:
    state["data"] = None
    state["filename"] = ""
    state["markdown"] = ""
    el("file-input").value = ""
    el("filename").textContent = "No file loaded"
    el("output").value = ""
    set_warnings([])
    set_status("Ready.")
    update_buttons()


el("file-input").bind("change", on_file_change)
el("dropzone").bind("dragover", on_drag_over)
el("dropzone").bind("dragleave", on_drag_leave)
el("dropzone").bind("drop", on_drop)
el("sample-button").bind("click", load_sample)
el("copy-button").bind("click", copy_output)
el("download-button").bind("click", download_output)
el("clear-button").bind("click", clear_output)
el("plain-toggle").bind("change", lambda _event: convert_current())

update_buttons()
