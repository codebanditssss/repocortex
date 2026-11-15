# Flask transfer pilot

The existing retrieval and learning pipeline runs on Flask, but this small pilot found **no learning gain**. It does not establish cross-repository generalization.

| Method | Correct function in top 10 | Correct file first | Function MRR |
| --- | ---: | ---: | ---: |
| BM25 | 4 of 7 | 3 of 7 | 0.338 |
| Dense | 4 of 7 | 3 of 7 | 0.480 |
| Dense + BM25, no graph | 4 of 7 | 3 of 7 | 0.562 |
| Frozen graph | 4 of 7 | 3 of 7 | 0.550 |
| Learned graph | 4 of 7 | 3 of 7 | 0.550 |

The learned graph tied the frozen graph at every checkpoint (0, 3, 6, 10, 13 fixes). The no-graph blend had slightly better MRR. These are counts from seven reports, not evidence of superiority or statistical equivalence.

## Data and controls

- 327 unique PR references scanned; 276 excluded because their diff did not map to 1–8 functions in the current `src/flask` snapshot.
- Of 51 eligible PR commits, 33 had no closing-issue reference. The remaining references supplied 20 unique issue reports.
- Queries use actual linked GitHub issue titles and bodies. No commit messages or PR descriptions substitute for missing issue reports.
- Chronological split grouped by fix commit: 13 training reports, 7 held out. The 40% holdout target was chosen before scoring because a 25% split left only four reports.
- The source graph contains 356 functions. All methods use the same candidate universe and issue queries. Model weights and ranking parameters transfer unchanged from the existing implementation; no Flask parameter search.
- Training outcomes are observed only after predictions. Held-out labels are used only for scoring. There are no co-change edges derived from either split, and issue IDs do not overlap between splits.
- This is an offline in-memory structural graph experiment. It makes no claim about hosted HydraDB performance or live learning persistence.

This remains retrospective: the current source snapshot contains later fixes, and issue bodies can have later edits. Explicit links and mapped functions select a narrow subset; linked issues can include feature requests. Changed functions are a proxy for fault location. Seven held-out reports are too few to conclude whether learning transfers.

## Reproduce

The frozen queries and labels are in `transfer_flask_dataset.json`; raw scores, paired intervals, provenance and exclusions are in `transfer_flask.json`. Check out the exact Flask snapshot recorded there, then run from the RepoCortex root:

```sh
OMP_NUM_THREADS=2 .venv/bin/python -m scripts.eval_transfer \
  --repo work/transfer/flask \
  --dataset results/transfer_flask_dataset.json \
  --output work/transfer/reproduced.json
```

Reproduction checks the checkout SHA and requires no GitHub API credentials. It uses the existing local sentence-transformers model (which may download if not cached). To remine, omit `--dataset`; that mode requires authenticated `gh` and records current GitHub issue bodies. The harness never connects to HydraDB or modifies the Django dataset or learned state.
