# doclens

**Coding agents can't read your `.docx`. doclens lets them, in Claude Code, Codex and OpenCode.**

> Status: early. M0 (eval set + smoke eval). The skill itself lands after the smoke numbers say it's worth it.

## The problem

Agents are handed specs in `.docx`, test data in `.xlsx`, decks in `.pptx` and papers in `.pdf`. Today they either
fail, guess, or improvise a throwaway `zipfile` + regex script, and every chart or diagram inside the document is
silently lost.

## The plan

One portable [agent skill](https://agentskills.io) built on [markitdown](https://github.com/microsoft/markitdown):

- every office format and PDF to Markdown, cached by content hash
- embedded images saved next to the Markdown, so the agent's own vision model opens them only when needed (no API keys)
- an explicit warning for scanned PDFs instead of empty output
- thin optional hooks per harness, shipped only where evals show the skill alone doesn't trigger reliably

## Evals first

We only ship what the numbers justify. The eval set is synthetic with exact answers, including facts that exist
only inside images.

```sh
python -m venv .venv && .venv/Scripts/pip install -r evals/requirements.txt   # or .venv/bin/pip
python tests/selfcheck.py                                                    # ground truth sanity
OPENROUTER_API_KEY=... python evals/smoke_eval.py --models <model-a> <model-b>
```

Results go to `evals/results/`.

## License

MIT
