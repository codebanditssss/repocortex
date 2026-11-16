# Prospective Starlette learning confirmation

**Decision: no demonstrated learning advantage.**

This study was registered before its first score. The online predict-then-learn stream moved in the expected direction, but the registered strict-accuracy endpoint on 24 untouched holdout fixes was exactly tied.

## What was frozen

- Repository: `Kludex/starlette` at `271c277da0ff64e2048a4d46ecc812b9d61db5f6`
- Dataset: 41 chronological training reports grouped into 36 fix commits, followed by 24 holdout reports with 24 distinct fix commits
- Arms: text only, frozen graph, flat fix memory, and learned graph
- Checkpoints: 0, 9, 18, 27 and 36 absorbed training fix groups
- Primary comparison: learned graph minus flat fix memory at the final fixed-holdout checkpoint
- Dataset SHA-256: `9c1dc4aa73c6d002c6997e89be003c655498dcfddc861fc5fb34f212798382f7`
- Registration SHA-256: `802467aaebdffd83b142b083af9e7d51e604b80124700ccfc85e5c2701573b85`
- Evaluator source manifest SHA-256: `10b93229f3940c12a3a358c702001be16acd782adac9c5c4d37a31586ca6b8e3`
- Embedding artifact manifest SHA-256: `3066ad97392f8bdc80b13775435b75b1aa5bcc1e3a414443aacd1ed94602d8fb`

The registration also locks the source snapshot, MiniLM revision and sentinel vector, Python runtime and packages, ranker parameters, fix-group order, failure behavior, bootstrap seed and decision rule. The split contains no shared ticket, commit or exact query across training and holdout. Its maximum cross-split five-token-shingle similarity is 0.201, below the registered 0.35 rejection threshold.

Every report sharing a fix commit was predicted in every arm before that outcome was revealed. Flat memory and the learned graph received the same prior fixes; only the learned graph applied graph operators. Text-only and frozen-graph arms never observed outcomes. There were no prediction failures, learning failures, retries or case replacements.

## Online predict-then-learn stream

| Arm | Reports | Strict function accuracy @10 | MRR@10 |
|---|---:|---:|---:|
| Text only | 41 | 29.3% | 0.390 |
| Frozen graph | 41 | 31.7% | 0.386 |
| Flat fix memory | 41 | 31.7% | 0.489 |
| Learned graph | 41 | 34.1% | 0.505 |

After grouping reports by their underlying fix, learned graph minus flat memory is:

| Metric | Difference | Paired 95% interval |
|---|---:|---:|
| Strict function accuracy @10 | +2.8 points | [0.0, 8.3] |
| MRR@10 | +0.0181 | [-0.0028, 0.0523] |

Both differences are directional and inconclusive. The intervals include zero.

## Untouched fixed holdout

The same 24 holdout fixes were rescored after each registered training checkpoint and were never learned from.

| Training fix groups absorbed | 0 | 9 | 18 | 27 | 36 |
|---|---:|---:|---:|---:|---:|
| Text-only strict accuracy | 54.2% | 54.2% | 54.2% | 54.2% | 54.2% |
| Frozen-graph strict accuracy | 54.2% | 54.2% | 54.2% | 54.2% | 54.2% |
| Flat-memory strict accuracy | 54.2% | 54.2% | 54.2% | 54.2% | 54.2% |
| Learned-graph strict accuracy | 54.2% | 54.2% | 54.2% | 54.2% | 54.2% |
| Flat-memory MRR | 0.507 | 0.507 | 0.507 | 0.502 | 0.523 |
| Learned-graph MRR | 0.507 | 0.500 | 0.500 | 0.511 | 0.529 |

At the final checkpoint, learned graph minus flat memory on the primary metric is **0.0 points**, with interval [0.0, 0.0]. All 24 fixes are ties, so the exact two-sided discordant-fix test is *p*=1.0. The registered success rule is not satisfied.

The secondary final MRR difference is +0.0062 with interval [0.0000, 0.0176]. It does not change the primary decision.

## What changed in the graph

The learned arm applied the registered operators during the stream:

| Operator | Applied operations |
|---|---:|
| Edge reweighting | 130 |
| Path compression | 134 |
| Gap ingestion | 61 |
| Entity merge or split | 18 |

Operator activity shows that the treatment ran. It does not by itself establish an accuracy improvement.

## Interpretation and limits

The prospective protocol prevents repository replacement, holdout tuning, selective retries and outcome-dependent stopping. That makes the null endpoint informative: this sample did not confirm that graph operators improve strict localization beyond retaining the same past fixes.

The earlier Django replay remains the established learning result: 45.1% frozen to 48.3% learned strict function accuracy@10, a +3.1 point paired difference with interval [0.9, 5.6]. Starlette supplies a prospective check, not evidence of consistent cross-repository transfer.

This Starlette sample has only 24 independent holdout fixes and is suited to detecting a large, consistent effect. A non-significant result is not evidence of equivalence. The final source snapshot can contain later fixes, issue bodies can have later edits, and diff-touched functions are a proxy for fault location. This was an offline ranking evaluation, not a live HydraDB request test or an agent-repair study.

## Evidence

- [Preregistration](starlette_prequential_registration.json)
- [Run receipt](starlette_prequential_run_receipt.json)
- [Raw outcomes and checkpoints](starlette_prequential_result.json)
- [Frozen dataset](starlette_track1_dataset.json)
- [Selection plan](starlette_track1_plan.md)
- [Protocol implementation](../scripts/register_prequential_track1.py)
- [Runner and summarizer](../scripts/run_prequential_track1.py)
