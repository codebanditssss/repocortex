# Registered Track 1 evaluation protocol

This protocol is for the next localization evaluation. It does not change or
reinterpret any published result. It makes the decision rules immutable before
scoring, so a positive result cannot come from prompt tuning, case replacement
or retrying failures.

## Question and arms

The primary question is whether the learned graph improves strict function
accuracy at ten over the same frozen graph. Text-only search is a second
baseline. All three arms receive the same report text, candidate functions,
source snapshot and case order:

1. `text_only`: dense plus BM25, with graph and memory scoring disabled.
2. `frozen_graph`: the source graph without fix outcomes or learned operators.
3. `learned_graph`: the frozen graph plus training-period outcomes and operators.

The primary estimand is learned minus frozen strict function accuracy at ten.
MRR@10 is secondary. Parameters must be fixed before registration. Holdout
labels cannot select a prompt, coefficient, checkpoint, repository or case.

## Freeze and leakage checks

`scripts/register_track1_eval.py` hashes every dataset, every tracked Python
source under `repocortex`, and the repository-ablation evaluator. The sorted
source manifest has its own digest. The registration also records Git HEAD and
any tracked changes to those sources; a clean worktree is recorded but not
required because the content hashes lock the actual bytes used. Missing,
duplicate, non-file and out-of-repository evaluator paths are rejected. It
creates a case ID from the repository, snapshot, fix, normalized query and gold
labels. It rejects non-chronological splits, shared tickets, shared commits,
exact query overlap and train/holdout query pairs whose five-token-shingle
Jaccard similarity is at least 0.35.

Register all repositories together, before scoring any of them:

```sh
python -m scripts.register_track1_eval \
  --dataset results/repository_ablations/httpx-dataset.json \
  --dataset results/repository_ablations/flask-dataset.json \
  --dataset results/repository_ablations/click-dataset.json \
  --dataset results/repository_ablations/werkzeug-dataset.json \
  --out /tmp/track1-registration.json
```

The registration file is immutable. If a dataset, snapshot, evaluator hash,
case ID, chronology or overlap check fails before scoring, abort that repository
instead of repairing the registration in place. A revised protocol requires a
new registration and must be reported as a separate study.

## Paired scoring and failures

Every registered case is scored once in every arm. Scores pair by immutable
case ID. After scoring starts, a timeout, provider error, harness error,
malformed outcome or missing outcome stays in the denominator and scores zero.
There is no outcome-dependent stopping, retry or case replacement. The report
shows each failure type and the number of completed cases in every arm.

Several reports can refer to one underlying fix. Confidence intervals therefore
use a paired cluster bootstrap by fix commit, with 10,000 resamples and the
registered seed. Each underlying fix receives equal weight. This avoids treating
multiple reports closed by one patch as independent evidence.

The scorer consumes a JSON file containing the registration digest and exactly
one record per case per arm. Completed records contain `function_acc@10` and
`mrr`; failure records contain a non-empty failure status:

```json
{
  "registration_sha256": "...",
  "repositories": [{
    "repository": "encode/httpx",
    "arms": {
      "text_only": [{"case_id": "...", "status": "completed", "function_acc@10": 1, "mrr": 0.5}],
      "frozen_graph": [{"case_id": "...", "status": "timeout"}],
      "learned_graph": [{"case_id": "...", "status": "completed", "function_acc@10": 1, "mrr": 1.0}]
    }
  }]
}
```

Summarize only after every registered outcome is present:

```sh
python -m scripts.summarize_track1_eval \
  --registration /tmp/track1-registration.json \
  --scores /tmp/track1-scores.json \
  --out /tmp/track1-summary.json
```

The summary can establish an advantage only if the learned-minus-frozen point
estimate is positive and its registered 95% interval excludes zero. Results
must still be described as retrospective localization on the named repositories,
not as proof that agents repair more bugs or that the live service improves.
