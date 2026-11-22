# doclens: Implementation Plan

> Local working doc. Not committed.

## 1. Problem

Coding agents (Claude Code, Codex, OpenCode) are increasingly handed non-text files: specs in `.docx`,
requirements/test data in `.xlsx`, decks in `.pptx`, papers/contracts in `.pdf`. Today:

- `.docx` / `.xlsx` / `.pptx` are unreadable binary to most agent `read` tools. The agent either fails, guesses,
  or improvises a one-off `python -c "..."` extraction every time.
- PDFs are read natively by some models (Claude, Gemini) but not by text-only models (many OpenRouter / local models),
  and native PDF input costs page-image tokens even when the text is all that matters.
- Images inside documents (charts, diagrams, screenshots) are silently lost by every text converter, including
  markitdown's defaults.

## 2. Goal

An agent handed any office document or PDF **reads it correctly, with fewer tokens, without silently losing content**,
the same way in Claude Code, Codex and OpenCode, with zero config and no API keys.

## 3. Positioning (why this, not existing tools)

| Existing | Gap doclens fills |
|---|---|
| `markitdown` CLI / `markitdown-mcp` | Raw converter; agent must decide to call it; images dropped; no cache; no warnings |
| Thin markitdown SKILL.md wrappers (≈10★) | Add nothing over the CLI |
| Anthropic `docx`/`xlsx`/`pptx`/`pdf` skills | Claude-only, editing-focused, one skill per format |
| docling / marker / MinerU | High-quality but heavy (ML models, GPU); overkill for "read this spec" |
| pullmd / huashu-md-html | Services or broad md↔html pipelines, not agent-native readers |

Differentiators: **one portable skill for every format, images extracted for on-demand viewing by the agent's own
vision model, hash cache, scanned-PDF detection, token report, measured evals.**

## 4. Scope

### In (v1)
- Formats: docx, xlsx, pptx, pdf (text), epub, html. Pass-through/skip for text & code.
- `doclens` script: convert → cached `.md` + `assets/` folder, prints a one-line summary.
- Images: extract embedded images (docx/pptx/xlsx) to `assets/`, placeholder with alt text, location, size, path.
  Skip tiny images (icons/logos), dedupe by hash.
- Scanned-PDF detection → explicit warning (no OCR).
- Portable `SKILL.md` (agentskills format).
- Optional thin nudge hooks per harness — shipped only where the trigger eval shows a gap.
- Eval harness (OpenRouter) + committed results.

### Out (and why)
- OCR, audio, YouTube: cloud services or heavy deps.
- Azure Document Intelligence / Content Understanding: paid account.
- Writing/editing documents: Anthropic skills already do it.
- Web service / REST / GUI: infra, and markitdown explicitly pushes those out of its own scope.
- PDF image extraction: deferred to v2 (needs pypdfium2 page/image extraction; decide from eval data).
- LLM captioning of images: opt-in v2 flag for text-only models.

## 5. Design

### 5.1 Core script: `skill/scripts/doclens.py`
```
python doclens.py <file> [--out DIR] [--no-images] [--max-chars N] [--json]
→ <out>/<sha256[:12]>/<name>.md
→ <out>/<sha256[:12]>/assets/img-001.png ...
stdout: "report.docx → report.md: 4.2k tokens (est), 3 images, 0 warnings\n<path>"
```
- Default out dir: `.doclens/` in CWD (cache keyed by content hash → repeat reads are free).
- Security: `MarkItDown(enable_plugins=False).convert_local(path)` only. Never `convert()` (URL fetch / SSRF).
  Reject paths that are not regular files.
- Size guard: if markdown > `--max-chars` (default 200k), write full file anyway, warn in summary, so the agent
  reads in ranges rather than the tool truncating content silently.
- Token estimate: `len(text) / 4` (shortcut: heuristic, swap for tiktoken only if someone needs exact counts).
- Exit codes: 0 ok, 1 conversion failed (message on stderr), 2 bad input.

### 5.2 Images
- markitdown `main` has an `_image_to_html(image_stream, stream_info, **kwargs)` override on Docx/Pptx/Xlsx
  converters. **Verify it exists in the PyPI release we pin (0.1.9).** If not:
  fallback = read OOXML zip `word/media/*`, `ppt/media/*`, `xl/media/*` directly and append an "Images" section
  (loses exact position, keeps content). Pick whichever works on the pinned release; don't support both.
- Placeholder format: `![<alt or "image">](assets/img-003.png) <!-- doclens: slide 4, 1200x800 -->`
- Skip images < 64×64 px or < 2 KB; dedupe by sha256.
- The agent opens images on demand with its own read/view tool (Claude Code `Read`, Codex image view,
  OpenCode `read`). No captioning API.

### 5.3 Scanned-PDF detection
- After conversion: if PDF and `chars / pages < 50` → warning
  `"looks scanned: little extractable text; consider native PDF input or OCR"`.
- Page count via `pypdfium2` (already a markitdown pdf extra dep? verify) or pdfminer.

### 5.4 SKILL.md
- Trigger description lists extensions explicitly (`.docx .xlsx .xls .pptx .pdf .epub`) and phrases
  ("spec document", "spreadsheet", "slide deck").
- Instructions: run script → read the `.md` → open `assets/*` only when the question needs a figure →
  respect warnings. Don't convert text/code files. For PDFs on vision models, small PDFs may be read natively.
- Install requirement: `pip install 'markitdown[docx,xlsx,pptx,pdf]'` or `uvx --from markitdown...`
  (decide after testing on Windows without uv).

### 5.5 Harness adapters (M4, only where needed)
| Harness | Packaging | Nudge mechanism |
|---|---|---|
| Claude Code | `.claude-plugin/plugin.json` + `skills/` + `hooks/hooks.json` | `PreToolUse` on `Read` for office exts → convert, rewrite `file_path` to the `.md` (`updatedInput`) — verify support |
| Codex | `.codex-plugin/plugin.json` + `hooks/hooks.json` (same schema) | `UserPromptSubmit`: detect doc paths in prompt → convert → `additionalContext` with the `.md` path (stay < 2.5k tokens) |
| OpenCode | `.opencode/plugins/doclens/` server plugin + skill | `session.hook("prompt")` swap attachment → `.md`; `tool.transform` update `read` for office exts |

Rule: hooks never inject document bodies; they point to the converted file.

## 6. Evaluations

### 6.1 Synthetic set (`evals/gen/`)
Deterministic generators with known answers (`answers.json`):
- docx (10): headings/sections, tables, nested lists, a chart image whose values appear nowhere in text.
- xlsx (8): multi-sheet, lookups ("Q3 total for region West"), formulas (cached values), merged cells.
- pptx (6): slide titles, speaker notes, tables, image with alt text, image-only facts.
- pdf (6): text-only, table-heavy, multi-column; 1 "scanned" (text rendered as image).
Each doc: 3–5 questions, exact-match answers; tag questions `text|table|image|structure`.

### 6.2 Content eval (`evals/content_eval.py`, OpenRouter)
Variants:
- **A raw**: file bytes as the harness would give them (PDF as native file part where supported; office → raw
  text dump / "cannot read").
- **B md**: markitdown default output.
- **C doclens**: doclens md with image placeholders, no images sent.
- **D doclens+img**: C plus the referenced images attached (simulates on-demand viewing).
- **E native PDF** (PDF only, vision models).
Models: 1 vision+native-PDF model (Claude Sonnet via OpenRouter), 1 cheap text-only model.
Metrics: accuracy per tag, input tokens, cost, failures. Judge: exact/normalized match; LLM judge only for free text.

### 6.3 Trigger eval (`evals/trigger_eval.py`)
~10 prompts × {Claude Code `claude -p`, `codex exec`, `opencode run`} × {skill only, skill+hook}.
Metric: % runs where the doc got converted, accuracy, tool-call count.

### 6.4 Decision rules (fixed before running)
- Ship at all: C/D beats A by ≥10pt accuracy on office docs, **or** equals A with ≥30% fewer tokens.
- Ship images-on-demand: D beats C by ≥15pt on `image` questions.
- Ship hook for harness X: skill-only conversion rate < 90% on X.
- If A ≈ C on native-PDF models: position as "office docs + text-only models"; say so in README.

## 7. Milestones (each = branch + PR)

| # | Branch | Deliverable | Exit criteria |
|---|---|---|---|
| M0 | `feat/scaffold-and-smoke-eval` | Skeleton, README, LICENSE, doc generator, smoke eval script | Generator produces docs + answers; tests pass |
| M1 | (same PR) | Smoke run: 5 docs × raw vs markitdown × 2 models | Numbers in `evals/results/smoke.md`; go/no-go |
| M2 | `feat/core-script` | `doclens.py`: convert, cache, images, scanned warning, tests | Self-check passes on generated set |
| M3 | `feat/skill-and-trigger-eval` | SKILL.md + trigger eval | Conversion rate per harness measured |
| M4 | `feat/adapters` | Plugins/hooks for harnesses below 90% | Trigger rate ≥ 90% with hook |
| M5 | `docs/results-and-release` | Full eval, README table, demo GIF, tag v0.1.0 | Published |

## 7.1 M1 outcome (2026-11-22): GO, with a sharper focus

Models: `anthropic/claude-haiku-5.5` (native file/vision), `deepseek/deepseek-v4-flash-0731` (text-only).

| model | naive | markitdown | md+img |
|---|---|---|---|
| haiku-5.5 | 11/15 | 13/15 | 15/15 |
| deepseek-v4-flash | 10/15 | 13/15 | n/a |

- Plain text conversion is a small win (+2–3 questions; misses: notes, sheet names). Alone it fails the "≥10pt" rule on Haiku.
- Images are decisive: 0/2 → 2/2. **Lead with images-on-demand, not with "markdown conversion".**
- Token rule: markitdown uses more prompt tokens than naive (structure costs tokens), so "saves tokens" is NOT a claim we can make vs naive. Measure vs native PDF in M5 instead.
- Noise: naive moved ±1 between identical temperature-0 runs → M5 needs ≥30 docs and 3 repeats.
- Bug found and fixed: `max_tokens=100` produced empty replies from reasoning models. Use 4000 and record `finish_reason`.
- Still unmeasured: agent effort (turns/tool calls to improvise extraction). That belongs in the M3 trigger eval and may be the second big win.
- md+img sent all doc images for every question. Real on-demand use is cheaper on non-image questions.

## 8. Risks / open questions
- ~~`_image_to_html` may be unreleased on PyPI~~ Verified present in markitdown 0.1.9 (docx + pptx). No fallback needed.
- Global Python on the dev box has a broken pandas → always use the repo `.venv`.
- Windows: no `uv` on the dev box → install instructions must work with plain `pip`.
- Claude Code `updatedInput` for `Read` — verify against current docs before M4.
- OpenRouter native PDF support differs by provider → variant E only where supported.
- Name `doclens` not checked on PyPI/npm.

## 9. Env
- `OPENROUTER_API_KEY` required for M1+.
- Python 3.10+; markitdown 0.1.9 (local dev uses editable clone at `C:\Users\berat\markitdown`).
