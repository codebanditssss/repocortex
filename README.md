# RepoCortex

RepoCortex is a code graph for bug localization. It stores files, classes,
functions, and the edges between them in HydraDB, ranks the functions a bug
report touches, and can reweight those edges from a repository's real fix
history. This repository is phase 1: the skeleton, a working graph load, and
baseline numbers on a time-ordered Django subset.

The held-out set is the newest slice of that history. BM25, a dense embedding
model, and a frozen graph are scored on it before any learning. Edge
reweighting then replays the earlier fixes in time order. Path compression,
gap-driven ingestion, and entity merge/split are stubbed for the next phase.

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

Function accuracy is strict: every gold function has to sit inside the top k. Replay prints a held-out checkpoint every 50 training issues. Only edge reweighting updates the graph. The other three operators return a stub result and leave the graph alone.

## Tests

```bash
python -m unittest discover -s tests
```

## What is not in this phase

An MCP server, a load test, and the dashboard are later phases. `GMI_API_KEY` is reserved and unused.
