# Documentation and results

This folder collects the evidence and results for the assignment.

## Evaluation results

The reproducible evaluation lives in [`eval/`](../eval):

- [`eval/REPORT.md`](../eval/REPORT.md) — what worked, what failed and why, known limitations,
  and the one-shot LLM comparison design.
- [`eval/transcripts.md`](../eval/transcripts.md) — full transcripts of 12 scripted
  conversations (25 turns) covering all three tasks, multi-turn follow-ups, an aggregate
  statistic, no-match cases, and a substitution with weak/conflicting evidence.
- [`eval/results.json`](../eval/results.json) — machine-readable pass/fail for all 57 checks.
- [`eval/run_eval.py`](../eval/run_eval.py) — re-run everything with `python eval/run_eval.py`.
- [`eval/llm_baseline.py`](../eval/llm_baseline.py) — one-shot LLM comparison (run with a
  `GEMINI_API_KEY`; produces `eval/llm_baseline.md`).

**Result: 57 / 57 checks pass.**

## Web UI verification

- [`ui-verification.md`](ui-verification.md) — the actual assistant output captured by driving
  the running Streamlit app (`app.py`) through a seven-turn session covering search + dairy
  follow-up, a detail view, an aggregate statistic, ingredient matching + exclusion follow-up,
  and an evidence-based substitution.