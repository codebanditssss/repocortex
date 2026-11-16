# HTTPX transfer replay

With the existing ranking settings unchanged, learning from 51 earlier HTTPX issue reports changes strict function accuracy@10 from **14/33 (42.42%) to 15/33 (45.45%)** on 33 later reports. The no-graph dense+BM25 control scores **13/33 (39.39%)**.

This is one additional correct held-out report. The paired 95% bootstrap interval for the learning gain is **0 to 9.09 percentage points**, including zero. File accuracy@1 does not improve. This is a modest positive exploratory transfer result, not established cross-repository generalization. The original flat Flask pilot remains published alongside it.

| Method | Strict function accuracy@10 | File accuracy@1 | MRR |
|---|---:|---:|---:|
| BM25 | 18.18% | 30.30% | 0.1938 |
| Dense | 36.36% | 57.58% | 0.3700 |
| Dense + BM25, no graph or memory | 39.39% | 51.52% | 0.4147 |
| Frozen graph | 42.42% | 51.52% | 0.4162 |
| Learned graph | 45.45% | 51.52% | 0.4189 |

All gold functions for a report must appear in the top ten for strict function accuracy. Function accuracy@5 is unchanged at 30.30%. Learning-minus-no-graph accuracy@10 is +6.06 points, with a paired 95% interval of -6.06 to +18.18 points.

## Selection and chronology

Repository: [encode/httpx](https://github.com/encode/httpx), snapshot `b5addb64f0161ff6bfe94c124ef76f6a1fba5254`, source scope `httpx`. The graph contains 434 indexed functions.

Before scoring, the run was fixed to a maximum of 300 eligible PR commits, a chronological last-40%-of-commits holdout, five replay checkpoints, and the existing Django ranking defaults. The repository history yielded only 259 eligible PR commits, so all were considered. No target-repository parameter tuning, holdout-driven selection, Django retraining, or additional runs seeking a better score were performed. A second run replays the exact frozen dataset as a reproducibility check.

Of 1,267 unique PR references scanned, 1,008 did not map to one through eight functions still present in the snapshot. Of the 259 eligible PRs, 175 had no explicit closing issue reference. There were 86 linked references; removing two repeated issue IDs left 84 reports. Reports come from GitHub issue titles and bodies, not commit messages.

The split has 51 training reports across 49 commits and 33 held-out reports across 33 commits. Latest training fix: Unix timestamp `1628864235`. Earliest held-out fix: `1637063266`. There are no shared issue IDs, commits, or exact lowercase whitespace-normalized report texts across the split. The evaluator checks the final learned memory contains exactly the training issue IDs.

Training checkpoints 0, 13, 26, 38, 51 score strict function accuracy@10 of 42.42%, 42.42%, 42.42%, 42.42%, 45.45%. MRR first dips before recovering slightly above its initial value. Operator counts are 112 gap-ingestion changes, 40 path-compression changes, one entity merge/split, and 135 edge reweights. Counts alone do not establish which operator caused the improvement.

## Reproduce

Use the repository Python environment with its existing embedding model cache. Clone HTTPX, check out the snapshot above, then run:

```sh
HF_HUB_OFFLINE=1 .venv/bin/python -m scripts.eval_transfer \
  --repo work/transfer/httpx --repository encode/httpx --scope httpx \
  --limit 300 --dataset results/transfer_httpx_dataset.json \
  --work work/transfer/httpx-eval \
  --output work/transfer/httpx-eval/reproduced.json
```

Omit `--dataset` to repeat mining with authenticated `gh`; live GitHub issue bodies and closing references may have changed. The published dataset is the reproducible input. JSON results include per-report scores, confidence intervals, snapshot and dataset hash, transferred parameters, selection counts, and split audit.

## Limits

This is an offline in-memory graph algorithm check; it does not query HydraDB or demonstrate hosted HTTPX learning. The fixed current code snapshot includes code from later fixes. Current issue bodies may contain later edits or solution discussion. Closing references can include feature requests. Excluding deleted/unmapped functions and PRs without explicit issue links introduces selection bias. Function mapping from fix diffs is a proxy for fault location, not human-labelled root cause. The audit catches exact normalized duplicates, not semantic duplicates. The sample is small and the confidence intervals include zero; do not describe the gain as statistically established.
