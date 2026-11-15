# Evaluation audit

The restored runtime reproduces the original 319-row results without retraining:
strict function accuracy@10 is **41.7% dense + BM25, 45.1% frozen graph, and
48.3% learned graph**. Strict accuracy requires every gold function for a fix to
appear in the top ten. These are offline replay results, not live HydraDB request
measurements or a comparison against other hackathon entries.

| Evaluation set | Rows | Dense + BM25 | Frozen graph | Learned graph |
|---|---:|---:|---:|---:|
| Original chronological fix-commit holdout | 319 | 41.69% | 45.14% | 48.28% |
| Excluding tickets also present in training | 316 | 42.09% | 45.57% | 48.73% |

The 316-row sensitivity check excludes two test rows for ticket **27489** and
one for **32980**. Both tickets occur in training memory. One 27489 row is a
revert whose commit subject references the old ticket. The data split is by
fix commit, so “319 previously unseen issues” would be inaccurate. There are
315 unique tickets in the original test set: 26434 appears three times, 36806
twice, and 27489 twice.

The learned-minus-frozen accuracy gap is **+3.13 percentage points** on the
original set (95% paired row-bootstrap interval **+0.94 to +5.64**). On the
316-row sensitivity set it is **+3.16 points** (**+0.63 to +5.70**). The learned
system exceeds dense + BM25 by **+6.58 points** (**+3.76 to +9.72**) on the
original set, and **+6.65 points** (**+3.80 to +9.49**) after exclusion.

## What was checked

- All 1,281 saved memory entries belong to training tickets; there was no replay
  or parameter fitting during verification.
- The base corpus contains no learned relations or non-unit edge weights.
- Dense + BM25 disables structural, memory, shortcut, file, and module bonuses.
- Frozen and learned settings agree with the saved tuning choice; the same
  embedding cache and query text are used across rankers.
- The recovered original report reproduced exactly before the pairing fix.

## Pairing correction

The shared bootstrap helper aligns rows by ticket ID, which is unsafe when a
ticket has several fixes with different gold functions. This evaluation script
now pairs the same ordered fix rows instead. Accuracy@10 and its intervals are
unchanged here, but MRR gaps change. For example, learned-minus-frozen MRR is
**0.027755**, matching the aggregate subtraction, rather than the recovered
report's 0.026188. `results/lexical_gap.json` contains corrected row-paired gaps.
The original recovered report remains in ignored `data/lexical-original.json`.

These intervals resample fix rows, not clusters of related tickets, and are
conditional on this dataset and fixed snapshot. The snapshot already includes
later fixes: this is retrospective localization, not a faithful historical
checkout for each issue. Removing seen tickets addresses one overlap; it does
not resolve snapshot leakage or establish performance on another repository.
The live demo can query structural edges through HydraDB while using cached
learned memory; its bounded traversal is not identical to this offline scorer.

## Reproduce

With the recovered runtime and embedding model available locally:

```bash
HF_HUB_OFFLINE=1 .venv/bin/python scripts/eval_lexical.py --output data/lexical-verification.json
HF_HUB_OFFLINE=1 .venv/bin/python scripts/eval_lexical.py --exclude-seen-tickets --output data/lexical-clean-verification.json
.venv/bin/python -m pytest tests/test_eval_lexical.py -q
```

Neither evaluation command retrains or writes to the graph database.
