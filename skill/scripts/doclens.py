"""doclens: convert a document to Markdown an agent can read, with embedded images saved for on-demand viewing.

Usage: python doclens.py FILE [--out DIR]

Writes  <out>/<hash>/<name>.md  and  <out>/<hash>/assets/img-<hash>.<ext>  (default out: ./.doclens).
Prints a one-line summary, then the Markdown itself when it is short enough to read inline.
Exit codes: 0 ok, 1 conversion failed, 2 bad input.
"""

import argparse
import base64
import hashlib
import io
import os
import re
import sys
from pathlib import Path

FORMAT_VERSION = "1"  # bump when output format changes, so stale cache entries are not reused
INLINE_LIMIT = 20_000  # chars; above this, print only the path so harness output limits don't truncate
LARGE_LIMIT = 200_000
MIN_IMAGE_PX = 64  # drop only images smaller than this on both sides (icons, bullets, tracking pixels); never by byte size, simple charts compress below 2 KB
SCANNED_CHARS_PER_PAGE = 50

# optional markdown title after the data URI: markdownify emits ![alt](data:... "title")
DATA_URI_IMAGE = re.compile(
    r'!\[([^\]]*)\]\(data:image/([a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)(?:\s+"(?:[^"\\]|\\.)*")?\)')
LEFTOVER_DATA_URI = re.compile(r"data:[\w/+.-]+;base64,[A-Za-z0-9+/=]{200,}")  # never let base64 reach the model


def file_hash(path):
    h = hashlib.sha256(FORMAT_VERSION.encode())
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def image_dims(data):
    try:
        from PIL import Image  # optional: present with the pptx extra; without it nothing is dropped
        with Image.open(io.BytesIO(data)) as im:
            return im.width, im.height
    except Exception:
        return None


def extract_images(markdown, assets):
    """Replace inline base64 images with files in assets/."""
    saved = set()

    def repl(m):
        alt, subtype, b64 = m.group(1), m.group(2).lower(), m.group(3)
        try:
            data = base64.b64decode(re.sub(r"\s", "", b64), validate=True)
        except ValueError:
            return f"![{alt}]()"
        dims = image_dims(data)
        if dims and max(dims) < MIN_IMAGE_PX:
            return ""
        ext = {"jpeg": "jpg", "svg+xml": "svg", "x-emf": "emf", "x-wmf": "wmf"}.get(subtype, subtype)
        name = f"img-{hashlib.sha256(data).hexdigest()[:8]}.{ext}"  # content hash also dedupes repeats
        if name not in saved:
            assets.mkdir(parents=True, exist_ok=True)
            (assets / name).write_bytes(data)
            saved.add(name)
        return f"![{alt or 'image'}](assets/{name}" + (f' "{dims[0]}x{dims[1]} px"' if dims else "") + ")"

    return LEFTOVER_DATA_URI.sub("data:(omitted)", DATA_URI_IMAGE.sub(repl, markdown))


def pdf_pages(path):
    try:
        from pdfminer.pdfpage import PDFPage
        with open(path, "rb") as f:
            return sum(1 for _ in PDFPage.get_pages(f))
    except Exception:
        return 0


def convert(src, out_root):
    """Return (md_path, cached). Raises on conversion failure."""
    from markitdown import MarkItDown

    fresh = not Path(out_root).exists()
    target = Path(out_root) / file_hash(src)
    md_path = target / f"{src.name}.md"
    if md_path.exists():
        return md_path, True

    # convert_local only: never let a document path turn into a URL fetch.
    md = MarkItDown(enable_plugins=False).convert_local(str(src), keep_data_uris=True).markdown
    md = extract_images(md, target / "assets")
    # shortcut: xlsx embedded images are not extracted (markitdown never emits them), add via _image_to_html if asked

    target.mkdir(parents=True, exist_ok=True)
    tmp = md_path.with_name(md_path.name + ".tmp")
    tmp.write_text(md, encoding="utf-8")
    os.replace(tmp, md_path)  # the .md is the cache marker, so it must never exist half-written
    if fresh:  # only a directory we created: --out pointing at the user's own folder must not get a catch-all ignore
        (Path(out_root) / ".gitignore").write_text("*\n", encoding="utf-8")
    return md_path, False


def warnings_for(src, md):
    warnings = []
    if src.suffix.lower() == ".pdf":
        pages = pdf_pages(src)
        if pages and len(md.strip()) / pages < SCANNED_CHARS_PER_PAGE:
            warnings.append(f"looks scanned ({pages} pages, almost no text): open the PDF natively or use OCR")
    if len(md) > LARGE_LIMIT:
        warnings.append("large document: read it in ranges")
    return warnings


def main(argv=None):
    p = argparse.ArgumentParser(description="Convert a document to agent-readable Markdown.")
    p.add_argument("file")
    p.add_argument("--out", default=".doclens")
    args = p.parse_args(argv)

    src = Path(args.file)
    if not src.is_file():
        print(f"doclens: not a file: {src}", file=sys.stderr)
        return 2
    try:
        md_path, cached = convert(src, args.out)
    except Exception as e:
        print(f"doclens: could not convert {src.name}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    md = md_path.read_text(encoding="utf-8")
    n_images = len(set(re.findall(r"\]\(assets/([^ )]+)", md)))
    print(f"{src.name} -> {md_path.resolve()} (~{len(md) // 4:,} tokens, {n_images} images{', cached' if cached else ''})")
    for w in warnings_for(src, md):
        print(f"warning: {w}")
    if n_images:
        print(f"images: {(md_path.parent / 'assets').resolve()} (open one only when the question needs it)")
    if len(md) <= INLINE_LIMIT:
        print("\n" + md)
    return 0


if __name__ == "__main__":
    # piped Windows stdout defaults to the legacy code page, which crashes on any non-ASCII document text
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
