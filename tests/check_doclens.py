"""Checks for skill/scripts/doclens.py. Run: python tests/check_doclens.py"""

import base64
import contextlib
import io
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw
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

    # icons (by pixels) are dropped, repeats deduped, small-but-real charts kept even when under 2 KB
    def png_b64(w, h, draw=False):
        im = Image.new("RGB", (w, h), "white")
        if draw:
            ImageDraw.Draw(im).rectangle([20, 20, w - 20, h - 20], fill=(60, 110, 200))
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        return buf.getvalue(), base64.b64encode(buf.getvalue()).decode()

    _, icon = png_b64(16, 16)
    chart_bytes, chart = png_b64(400, 250, draw=True)
    assert len(chart_bytes) < 2048, "test chart should be smaller than the old byte threshold"
    md = doclens.extract_images(f"![i](data:image/png;base64,{icon}) ![b](data:image/png;base64,{chart}) "
                                f"![c](data:image/png;base64,{chart})", tmp / "a")
    assert md.count("](assets/") == 2 and len(list((tmp / "a").iterdir())) == 1, md
    assert '"400x250 px"' in md and "![i]" not in md

    # titled data-URI image (html/epub) must not leave base64 behind; unknown data URIs are scrubbed too
    (tmp / "t.html").write_text(f'<p>x</p><img src="data:image/png;base64,{chart}" alt="chart" title="Rev &quot;Q3&quot;">')
    code, out = run(tmp / "t.html", "--out", cache)
    assert code == 0 and "base64" not in out and "![chart](assets/" in out, out[:300]
    leftover = doclens.extract_images("[doc](data:application/pdf;base64," + "A" * 400 + ")", tmp / "b")
    assert "AAAA" not in leftover and "data:(omitted)" in leftover, leftover

    # --out pointing at an existing folder must not get a catch-all .gitignore; no temp files left behind
    mine = tmp / "mine"
    mine.mkdir()
    assert run(tmp / "t.html", "--out", mine)[0] == 0
    assert not (mine / ".gitignore").exists()
    assert not list(cache.rglob("*.tmp")) and not list(mine.rglob("*.tmp"))

    # non-ASCII text through a pipe (an agent's shell) must not crash on the legacy Windows code page
    (tmp / "u.html").write_text("<p>Şeker → ğüşiöç 日本語</p>", encoding="utf-8")
    r = subprocess.run([sys.executable, doclens.__file__, str(tmp / "u.html"), "--out", str(tmp / "cu")],
                       capture_output=True)
    assert r.returncode == 0 and "Şeker → ğüşiöç 日本語" in r.stdout.decode("utf-8"), r.stderr.decode(errors="replace")

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
