# doc2md Brython demo

Static browser wrapper for `doc2md.convert_bytes(...)`. It does not modify or
bundle the Python package. The page accepts only legacy Word 97-2003 binary
`.doc` files.

## Run

Serve the repository root over HTTP:

```bash
python -m http.server 8000
```

Open:

```text
http://localhost:8000/browser-brython/
```

The page loads `doc2md` from GitHub through jsDelivr:

```text
https://cdn.jsdelivr.net/gh/vertuzz/doc2md@main/src
```

The page loads Brython from jsDelivr and reads selected files with the browser
File API, then passes the bytes to `convert_bytes(...)`.

The `Load sample` button decodes `sample.doc.b64`, a tiny synthetic legacy `.doc`
fixture stored as text so the Git repository does not need committed `.doc`
binary files.

## Notes

Brython 3.14.3 does not ship `xml.etree.ElementTree`, so this wrapper includes a
tiny import-time shim under `pycompat/`. The browser UI rejects DOCX, DOCM, RTF,
HTML, and other non-OLE2 inputs so the public page stays focused on legacy
binary `.doc` conversion.
