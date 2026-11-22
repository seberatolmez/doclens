"""Checks for skill/scripts/doclens.py. Run: python tests/check_doclens.py"""

import base64
import contextlib
import io
import sys
import tempfile
import zipfile
from pathlib import Path

from PIL import Image
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "skill" / "scripts"), str(ROOT / "evals" / "gen")]
import doclens  # noqa: E402
from generate import generate  # noqa: E402


def run(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = doclens.main([str(a) for a in args])
    return code, out.getvalue()


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    data, cache = tmp / "data", tmp / "cache"
    generate(data)

    # images: saved as files, alt text kept, bytes identical to the embedded media
    for doc, media_prefix in [("deck.pptx", "ppt/media/"), ("spec.docx", "word/media/")]:
        code, out = run(data / doc, "--out", cache)
        assert code == 0, out
        md_path = Path(out.split(" -> ")[1].split(" (")[0])
        md = md_path.read_text(encoding="utf-8")
        assert "base64" not in md, f"{doc}: data URI left in markdown"
        assets = list((md_path.parent / "assets").iterdir())
        assert len(assets) == 1, f"{doc}: expected 1 image, got {assets}"
        assert f"](assets/{assets[0].name}" in md
        with zipfile.ZipFile(data / doc) as z:
            embedded = [z.read(n) for n in z.namelist() if n.startswith(media_prefix)]
        assert assets[0].read_bytes() in embedded, f"{doc}: saved image differs from embedded"
    assert "![Org chart](assets/" in (next(cache.glob("*/deck.pptx.md"))).read_text(encoding="utf-8")
    assert (cache / ".gitignore").read_text() == "*\n"

    # cache hit
    code, out = run(data / "deck.pptx", "--out", cache)
    assert code == 0 and "cached" in out.splitlines()[0]

    # spreadsheets convert, small docs are printed inline
    code, out = run(data / "sales.xlsx", "--out", cache)
    assert code == 0 and "## 2025" in out and "| West |" in out, out

    # tiny images (icons) are dropped, repeats deduped
    tiny = base64.b64encode(b"\x89PNG" + b"0" * 100).decode()
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), "red").save(buf, "PNG")
    big = base64.b64encode(buf.getvalue() + b"\0" * 3000).decode()
    md = doclens.extract_images(f"![a](data:image/png;base64,{tiny}) ![b](data:image/png;base64,{big}) "
                                f"![c](data:image/png;base64,{big})", tmp / "a")
    assert md.count("](assets/") == 2 and len(list((tmp / "a").iterdir())) == 1, md
    assert '"300x200 px"' in md

    # text PDF: no warning; scanned (image-only) PDF: warning, also on cache hit
    c = canvas.Canvas(str(tmp / "text.pdf"))
    for page in range(2):
        c.drawString(72, 720, f"Page {page + 1}: the refund window is 30 days for all EU customers.")
        c.showPage()
    c.save()
    code, out = run(tmp / "text.pdf", "--out", cache)
    assert code == 0 and "warning" not in out and "refund window" in out, out
    img = Image.new("RGB", (1200, 1600), "white")
    img.save(tmp / "scan.pdf", "PDF", save_all=True, append_images=[img.copy()])
    for _ in range(2):
        code, out = run(tmp / "scan.pdf", "--out", cache)
        assert code == 0 and "looks scanned (2 pages" in out, out

    # bad input / unconvertible input
    assert run(tmp / "missing.docx")[0] == 2
    (tmp / "blob.bin").write_bytes(bytes(range(256)) * 64)
    assert run(tmp / "blob.bin", "--out", cache)[0] == 1

print("ok: doclens checks passed")
