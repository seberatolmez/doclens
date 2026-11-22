"""Smoke eval (M1): does markitdown output beat what an agent improvises today?

Variants per document:
  naive       - unzip the OOXML and strip tags (what agents typically improvise with zipfile + regex)
  markitdown  - markitdown default output

Usage:
  set OPENROUTER_API_KEY=...
  python evals/smoke_eval.py --models anthropic/claude-sonnet-4.5 meta-llama/llama-3.3-70b-instruct
Writes evals/results/smoke.json and evals/results/smoke.md.
"""

import argparse
import base64
import json
import os
import re
import sys
import zipfile
from pathlib import Path

import requests
from markitdown import MarkItDown

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "gen"))
from generate import generate  # noqa: E402

OOXML_PARTS = re.compile(r"^(word/document|ppt/slides/slide\d+|xl/sharedStrings|xl/worksheets/sheet\d+)\.xml$")
SYSTEM = "Answer the question using only the document. Reply with the answer only, no explanation."


def naive_extract(path):
    with zipfile.ZipFile(path) as z:
        names = sorted((n for n in z.namelist() if OOXML_PARTS.match(n)),
                       key=lambda n: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", n)])
        xml = " ".join(z.read(n).decode("utf-8", "replace") for n in names)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", xml)).strip()


def markitdown_extract(path):
    return MarkItDown(enable_plugins=False).convert_local(str(path)).markdown


def media_images(path):
    """Embedded images as data URLs: what doclens will save to assets/ for the agent to open."""
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if re.match(r"^(word|ppt|xl)/media/.+\.(png|jpe?g)$", n, re.I))
        return [f"data:image/{n.rsplit('.', 1)[1].lower().replace('jpg', 'jpeg')};base64,"
                + base64.b64encode(z.read(n)).decode() for n in names]


VARIANTS = {"naive": naive_extract, "markitdown": markitdown_extract, "md+img": markitdown_extract}
IMAGE_VARIANTS = {"md+img"}


def norm(s):
    return re.sub(r"[^a-z0-9.]", "", s.lower())


def ask(model, document, question, key, images=()):
    text = f"<document>\n{document}\n</document>\n\nQuestion: {question}"
    content = [{"type": "text", "text": text}] + [{"type": "image_url", "image_url": {"url": u}} for u in images]
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "temperature": 0,
            "max_tokens": 4000,  # reasoning models spend tokens thinking; a low cap returns empty answers
            "usage": {"include": True},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": content if images else text},
            ],
        },
        timeout=120,
    )
    r.raise_for_status()
    body = r.json()
    usage = body.get("usage", {})
    choice = body["choices"][0]
    return (choice["message"]["content"] or "", usage.get("prompt_tokens", 0), usage.get("cost", 0.0),
            choice.get("finish_reason"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--models", nargs="+", required=True)
    p.add_argument("--vision", nargs="*", default=[], help="models that also get the md+img variant")
    p.add_argument("--data", default=str(ROOT / "data"))
    args = p.parse_args()
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("OPENROUTER_API_KEY is not set")

    answers = generate(args.data)
    docs = {a["doc"] for a in answers}
    texts = {(d, v): fn(Path(args.data) / d) for d in docs for v, fn in VARIANTS.items()}
    images = {d: media_images(Path(args.data) / d) for d in docs}

    rows = []
    for model in args.models:
        for v in VARIANTS:
            if v in IMAGE_VARIANTS and model not in args.vision:
                continue
            for a in answers:
                imgs = images[a["doc"]] if v in IMAGE_VARIANTS else ()
                try:
                    reply, tokens, cost, finish = ask(model, texts[(a["doc"], v)], a["question"], key, imgs)
                    error = None
                except requests.RequestException as e:
                    reply, tokens, cost, finish, error = "", 0, 0.0, None, str(e)
                ok = norm(a["answer"]) in norm(reply)
                rows.append({**a, "model": model, "variant": v, "reply": reply, "correct": ok,
                             "prompt_tokens": tokens, "cost": cost, "finish_reason": finish, "error": error})
                print(f"{model:40} {v:10} {a['id']:22} {'OK ' if ok else 'BAD'} {reply[:60]!r}")

    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    (out / "smoke.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    (out / "smoke.md").write_text(report(rows), encoding="utf-8")
    print(report(rows))


def report(rows):
    tags = sorted({r["tag"] for r in rows})
    lines = ["| model | variant | accuracy | " + " | ".join(tags) + " | avg prompt tokens | cost $ |",
             "|---|---|---|" + "---|" * len(tags) + "---|---|"]
    for model in dict.fromkeys(r["model"] for r in rows):
        for v in VARIANTS:
            rs = [r for r in rows if r["model"] == model and r["variant"] == v]
            if not rs:
                continue
            acc = lambda xs: f"{sum(x['correct'] for x in xs)}/{len(xs)}" if xs else "-"  # noqa: E731
            per_tag = [acc([r for r in rs if r["tag"] == t]) for t in tags]
            avg_tok = sum(r["prompt_tokens"] for r in rs) // max(len(rs), 1)
            cost = sum(r["cost"] or 0 for r in rs)
            lines.append(f"| {model} | {v} | {acc(rs)} | " + " | ".join(per_tag) + f" | {avg_tok} | {cost:.4f} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
