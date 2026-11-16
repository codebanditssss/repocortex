# Cross-repository graph and memory controls

These are offline retrospective localization evaluations, not live HydraDB queries or completed agent repairs. Parameters were not tuned on these holdout reports. Click and Werkzeug were selected and their datasets frozen before scoring; HTTPX and Flask were existing evaluation sets.

Strict function accuracy at ten requires every mapped changed function for a report to appear in the first ten candidates.

| Repository | Training reports | Text only | Frozen graph | Flat fix memory | Learned graph | Learned, traversal off |
|---|---:|---:|---:|---:|---:|---:|
| httpx | 51 | 13/33 | 14/33 | 14/33 | 15/33 | 14/33 |
| flask | 13 | 4/7 | 4/7 | 4/7 | 4/7 | 4/7 |
| click | 44 | 18/37 | 21/37 | 18/37 | 21/37 | 18/37 |
| werkzeug | 26 | 9/16 | 8/16 | 9/16 | 9/16 | 9/16 |

HTTPX improves by one report over frozen graph. Flask is flat. Click's gain over text is already present in the frozen graph: additional learning adds no strict-accuracy gain. Werkzeug recovers one frozen-graph miss but only matches text-only search. These results do not establish a consistent learning advantage across repositories.

## Controls and limitations

All arms share candidate functions and queries. Flat memory receives exactly the same earlier training reports and known fixes, without graph traversal or learning operators. The traversal-off arm retains the full learned memory, including learned FIXED_IN weights, but disables structural and shortcut scoring. Only training outcomes reach learning operators. Five checkpoints score the same holdout without feeding its labels back.

The current source snapshot can contain later fixes and current issue descriptions can contain later edits. Mapped changed functions are a proxy for fault location. Cross-split ticket, commit and exact normalized-query overlaps are rejected; semantic duplicates are not detected. Click's 37 holdout reports represent 24 distinct fix commits, so issue-level bootstrap intervals in the JSON are exploratory and should not be interpreted as independent-observation confidence bounds. Other holdouts have distinct commits per report. MRR fields are **MRR@10**.

## Reproduction

Install this repository's Python dependencies, clone the named upstream repository, and check out the exact `snapshot` in its dataset. For each of `httpx`, `flask`, `click`, and `werkzeug`, run:

```sh
python -m scripts.eval_repository_ablation \
  --repo /path/to/upstream-checkout \
  --dataset results/repository_ablations/httpx-dataset.json \
  --out /tmp/httpx-new-evidence.json
```

Use the corresponding dataset filename for each repository and a fresh output path. The evaluator rejects indexed files that differ from HEAD, including ignored Python files. Each result records the dataset digest, consumed-source manifest, evaluator and imported package source hashes, sample counts, individual predictions, paired intervals and the learning curve. The local embedding model is sentence-transformers/all-MiniLM-L6-v2; its remote revision was not pinned for these runs, which limits exact bitwise reproducibility.

- [httpx raw results](repository_ablations/httpx.json) · [frozen dataset](repository_ablations/httpx-dataset.json)
- [flask raw results](repository_ablations/flask.json) · [frozen dataset](repository_ablations/flask-dataset.json)
- [click raw results](repository_ablations/click.json) · [frozen dataset](repository_ablations/click-dataset.json)
- [werkzeug raw results](repository_ablations/werkzeug.json) · [frozen dataset](repository_ablations/werkzeug-dataset.json)
