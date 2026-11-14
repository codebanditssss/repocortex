# RepoCortex

RepoCortex is a code graph for bug localization. It stores files, classes,
functions, and the edges between them in HydraDB, ranks the functions a bug
report touches, and updates that graph from the repository's fix history.
Ranking starts from a dense embedding plus a small BM25 blend. Replaying older
fixes in time order then adds shortcut and fix edges, and only the edges that
actually moved a hit get credit or a debit.

## Layout

- `repocortex/` graph builder, HydraDB client, retrieval, learner, eval
- `scripts/` mine, ingest, evaluate
- `data/` local checkouts and caches (gitignored)
- `results/` metrics and the curve plot
- `web/` placeholder for the later Next.js dashboard
- `docker-compose.yml` self-hosted HydraDB 0.4.0

## HydraDB

Two adapters sit behind one client.

- `bolt` talks to open-source HydraDB 0.4.0 (`ghcr.io/hydra-db/hydradb:0.4.0`) with the Neo4j Bolt driver. This is the default and the one the phase 1 numbers were produced with.
- `hosted` talks to `POST https://api.hydradb.com/byog/query` with `Authorization: Bearer` and `API-Version: 2`. It needs `HYDRADB_API_KEY`. The hosted openCypher dialect is wider (undirected variable-length walks, indexes). The OSS engine is not: one relationship type per pattern, bounded `*1..N`, integer node ids, batched `UNWIND`, and no APOC. Personalized PageRank runs in this process either way.

Reads are paged and compared to `count(*)` so a silent truncation is visible in `results/graph_stats.json`.

### Start the local engine

```bash
mkdir -p data/hydradb/store data/hydradb/cache
printf '%s\n' 'local-development-token-32-bytes' > data/hydradb/auth-token
docker compose up -d hydradb
```

The password in `.env.example` is the public local-development token from the HydraDB docs, not a cloud key. Wait until `http://127.0.0.1:9090/readyz` returns 200 and `http://127.0.0.1:8443/healthz` returns `{"status":"ok"}`.

Copy `.env.example` to `.env` if you want to override the defaults. The defaults already point at the local Bolt port.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

The dense baseline downloads `sentence-transformers/all-MiniLM-L6-v2` on first use.

## Data

The miner reads a local Django checkout. A blobless sparse clone of the two packages we index is enough:

```bash
git clone --filter=blob:none --sparse https://github.com/django/django.git data/django
git -C data/django sparse-checkout set django/db django/forms
```

It keeps commits whose subject matches `Fixed #NNNN`, maps diff hunks to the enclosing function, and drops a commit when those functions are gone from the chosen snapshot or when the fix touches more than 8 functions. Ticket text comes from `code.djangoproject.com` and is cached under `data/trac/`. The newest 20% of commits, by commit rather than by ticket, is the held-out split.

```bash
python scripts/mine_django.py --limit 400
```

`--limit` is the number of issues to keep. Scope defaults to `django/db,django/forms` (`REPOCORTEX_SCOPE`).

## Graph and eval

```bash
python scripts/smoke_hydradb.py
python scripts/build_graph.py
python scripts/run_eval.py --replay
```

`scripts/run_phase1.py --limit 400` runs smoke, mine, ingest, baselines, and replay in that order.

`build_graph.py` parses the snapshot with the Python `ast` module, adds `CO_CHANGED` edges from the training commits only, and batch-loads nodes and edges. Every edge starts at `w=1.0` with zero hits and misses.

`run_eval.py` writes:

- `results/baselines.json` with function Acc@5, Acc@10, file Acc@1, Acc@5, and MRR
- `results/curve.json` and `results/curve.png` when `--replay` is set
- `results/provenance.json` with the path behind each top hit on the holdout

Function accuracy is strict: every gold function has to sit inside the top k. Replay prints a held-out checkpoint every 40 training issues. Four operators run on each training issue, after the prediction and before the fix is stored:

- edge reweight credits a path that reached gold and debits a path that promoted a wrong top-k hit. Nearby edges that did not change the ranking are left alone. Weights decay back toward 1.
- path compression writes a `SHORTCUT` once a concept or symptom has landed on the same function at least three times with precision at least 0.4.
- gap ingestion, when gold is outside the frontier, links a same-file neighbor and a matching test, and counts two specific report tokens toward a later shortcut.
- entity merge writes `SAME_AS` for concepts that fix the same functions, and `REFINES` when one concept is too broad.

The learned ranker does not walk the whole neighborhood on every query. Its score is the dense score, plus a BM25 blend of 0.10, plus a bonus from similar past fixes (`FIXED_IN`) and from shortcuts. The blend was chosen on the last 40 training issues, which are still before the holdout. At step 0 there is no fix history and no shortcut, so that checkpoint is the unlearned hybrid.

Frozen retrieval is still scored on its own. It restarts PageRank with probability 0.5 and mixes in the BM25 score of the same candidates (weight 0.35). Without that, hub functions such as `Collector.add` outrank the seeds. The walk is not bit-stable across runs.

## Results from this run

Snapshot `f24f38c6b282`, scope `django/db` and `django/forms`, 400 issues (320 train, 80 held out). The graph loaded into local HydraDB 0.4.0 with no truncated pages: 4989 nodes and 21532 edges (3105 functions).

Held-out baselines, before the replay:

| ranker | fn Acc@5 | fn Acc@10 | file Acc@1 | file Acc@5 | MRR |
|---|---:|---:|---:|---:|---:|
| BM25 | 0.225 | 0.3125 | 0.3375 | 0.675 | 0.258 |
| dense (MiniLM) | 0.3125 | 0.3875 | 0.400 | 0.7625 | 0.307 |
| frozen graph | 0.2125 | 0.3125 | 0.300 | 0.600 | 0.220 |

The frozen graph does not beat dense. On this run it also does not beat BM25 at function Acc@10 (both 0.3125). An earlier frozen run landed a little higher (function Acc@10 0.325) because the bounded path sampler is not bit-stable. Either way the unlearned walk stays under the dense line.

The learning curve on the same 80 issues:

| step | fn Acc@5 | fn Acc@10 | file Acc@1 | MRR |
|---:|---:|---:|---:|---:|
| 0 | 0.375 | 0.400 | 0.450 | 0.371 |
| 120 | 0.3625 | 0.400 | 0.450 | 0.365 |
| 200 | 0.375 | 0.425 | 0.4875 | 0.383 |
| 320 | 0.3875 | 0.4375 | 0.500 | 0.395 |

Step 0 is already above dense because of the BM25 blend (function Acc@10 0.400 vs 0.3875, MRR 0.371 vs 0.307). Learning then lifts function Acc@10 to 0.4375 and MRR to 0.395. MRR dips at step 120 (0.365) and recovers. File Acc@1 moves from 0.450 to 0.500. The full series is in `results/curve.json` and `results/curve.png`.

The replay wrote 597 `FIXED_IN` edges and 60 `SHORTCUT` edges into local HydraDB. Credit or debit touched 232 edges. Path compression fired 107 times, gap ingestion 474 times, and merge/split 3 times. A holdout path looks like `issue #35575 sim 0.75 -FIXED_IN-> UniqueConstraint.validate`. `GMI_API_KEY` was unset, so no LLM call was made.

## Tests

```bash
python -m unittest discover -s tests
```

## What is not in this phase

An MCP server, a load test, and the dashboard are later phases. `GMI_API_KEY` is reserved and unused.
