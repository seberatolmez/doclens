"""Self-check for the eval set. Run: python tests/selfcheck.py

Asserts the ground truth is sound:
- every non-image answer is extractable by markitdown (otherwise the question is unfair),
- every image answer is NOT in markitdown output (proves the image gap the eval measures).
"""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "evals" / "gen"))
from generate import GENERATORS, generate  # noqa: E402
from smoke_eval import markitdown_extract, naive_extract, norm  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    answers = generate(tmp)
    assert {a["doc"] for a in answers} == set(GENERATORS)
    md = {d: norm(markitdown_extract(Path(tmp) / d)) for d in GENERATORS}
    for a in answers:
        found = norm(a["answer"]) in md[a["doc"]]
        if a["tag"] == "image":
            assert not found, f"image-only answer leaked into text: {a['id']}"
        else:
            assert found, f"answer not extractable by markitdown: {a['id']} -> {a['answer']}"
        assert naive_extract(Path(tmp) / a["doc"]), f"naive extraction empty: {a['doc']}"

print(f"ok: {len(answers)} questions across {len(GENERATORS)} documents")
