# eval/ — the WITH/WITHOUT evidence engine (Track B)

The number the roadmap hinges on: **does putting Sembl in the loop reduce bad merges,
without over-firing on good ones?** This directory measures exactly that, deterministically.

## Layout
- `../docs/eval-metric-O3.md` — **B1**, the metric, defined before any run (read this first).
- `build_corpus.py` — **B2**, regenerates the captured corpus under `corpus/`.
- `corpus/<NN-name>/case.json` — one captured case: a diff + untrusted report + declared
  bounds + a label (the violation it contains) + the verdict the gate should return.
- `harness.py` — **B3**, runs every case through the real gate and prints WITH vs WITHOUT.

## Run it
```bash
# from the repo root, on the shared venv (no model, no MCP server needed)
python eval/harness.py            # prints the table; exit 1 if the gate drifts from labels
python eval/harness.py --json     # machine-readable summary
python eval/build_corpus.py       # regenerate corpus/ from build_corpus.py
```

## Current result (12 captured cases: 8 bad, 4 clean)
| metric | WITHOUT | WITH |
|---|---|---|
| bad-merge rate (headline, lower better) | 1.00 | **0.25** |
| false-alarm rate (cost, must stay low) | 0.00 | **0.00** |
| caught rate (hard BLOCK) | — | **0.75** |

The gate hard-blocks 6/8 bad changes (out-of-scope, forbidden, fabricated) and WARN-flags
the other 2 (unevidenced, over-churn) — so bad changes reaching "merged" fall from 100% to
25%, with zero clean changes blocked. Honest limits: WARN-flagged changes still merge (the
gate is advisory on those), and the cost / iterations-to-green arm (O3 §3.4–3.5) is fed by
live-loop runs via the C1.3 run-store, not these single-shot captured diffs.
