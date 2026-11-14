# RepoCortex

RepoCortex is a code graph for bug localization. It stores files, classes,
functions, and the edges between them in HydraDB, ranks the functions a bug
report touches, and updates that graph from the repository's fix history.
Ranking starts from dense and BM25 seeds, then one hop on the code graph.
Replaying older fixes in time order stores those fixes and updates the edges
that actually moved a hit.

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

The miner reads a local Django checkout. The indexed tree is the whole `django/` package, including contrib, plus `tests/` so `TESTED_BY` edges exist. Test functions are not gold. A commit that only changes tests is dropped.

```bash
git clone --filter=blob:none --sparse https://github.com/django/django.git data/django
git -C data/django sparse-checkout set django tests
```

It keeps commits whose subject matches `Fixed #NNNN`, maps diff hunks to the enclosing function, and drops a commit when those functions are gone from the chosen snapshot or when the fix touches more than 8 functions. Ticket text comes from `code.djangoproject.com` and is cached under `data/trac/`. The newest 20% of commits, by commit time rather than by ticket number, is the held-out split. Replay walks the training issues oldest first.

```bash
python scripts/mine_django.py --limit 1600
```

`--limit` is the number of issues to keep. Scope defaults to `django,tests` (`REPOCORTEX_SCOPE`). Pass `--force` to rebuild `data/dataset.json`.

## Graph and eval

```bash
python scripts/smoke_hydradb.py
python scripts/build_graph.py --reset
python scripts/run_eval.py --replay
```

`--reset` deletes the previous graph before ingest, so a wider scope does not keep stale nodes. `build_graph.py` parses the snapshot with the Python `ast` module, adds `CO_CHANGED` edges from the training commits only, and batch-loads nodes and edges. Every structural edge starts at `w=1.0`.

`run_eval.py --replay` writes:

- `results/baselines.json` with function Acc@5, Acc@10, file Acc@1, Acc@5, and MRR, each with a 95% bootstrap interval
- `results/curve.json` and `results/curve.png` for the holdout ablations and the prequential series
- `results/provenance.json` with the path behind each top hit on the holdout
- `results/graph.json` with nodes and edges, including learned edges and weights
- `results/snapshots.json` at each checkpoint, with metrics and the edges added since the previous step

Function accuracy is strict: every gold function has to sit inside the top k. MRR is the reciprocal rank of the first gold function, and it is 0 when that function is outside the top 10. Intervals are a percentile bootstrap of the mean, 1000 resamples, seed 7. The learned-minus-dense gap resamples the same holdout issues for both systems.

The score at step 0 is the frozen graph. Seeds are the top dense hits and the top BM25 hits. One hop over `CALLS`, `CO_CHANGED`, `TESTED_BY`, and `DEFINES` is mixed in at `graph_mix` 0.05, and each seed is divided by the square root of its degree. A BM25 blend of 0.10 is added to the dense score. That blend was chosen on the last 40 training issues of the smaller phase 2 split. `graph_mix` was not fit on the holdout. This is not the older PageRank walk.

Replay then stores each training fix and runs the operators, oldest first. Checkpoints are about 15, evenly spaced, including step 0 and the last issue. The same holdout is scored at every checkpoint. Five lines are drawn:

- learning off: the frozen score, with no fix stored
- reweight: store the fix (`FIXED_IN`) and reweight edges that reached gold or promoted a wrong top-k hit
- +shortcuts: also write a `SHORTCUT` after support of 3 and precision of at least 0.4
- +gap: also link a same-file neighbor and a matching test when gold is outside the frontier
- full: also `SAME_AS` and `REFINES`

Every learning line stores the fix. Reweighting has nothing to update until that memory exists. Weights decay back toward 1.

Prequential accuracy scores each training issue before the operators see it. `results/curve.json` stores the raw hit and a rolling window of 100. The plot starts once that window is full, so the first points are not a ramp from zero.

## Results from this run

Snapshot `f24f38c6b282`, scope `django` and `tests`, 1600 issues (1281 train, 319 held out). The graph loaded into local HydraDB 0.4.0 with no truncated pages: 46443 nodes and 138150 edges (8834 functions, 21603 tests, 13686 `TESTED_BY`). `GMI_API_KEY` was unset, so no LLM call was made.

Held-out scores. Brackets are 95% bootstrap intervals.

| ranker | fn Acc@5 | fn Acc@10 | file Acc@1 | file Acc@5 | MRR |
|---|---:|---:|---:|---:|---:|
| BM25 | 0.273 [0.223, 0.323] | 0.329 [0.276, 0.382] | 0.345 [0.298, 0.398] | 0.618 [0.561, 0.671] | 0.324 [0.282, 0.366] |
| dense (MiniLM) | 0.292 [0.238, 0.342] | 0.373 [0.317, 0.426] | 0.357 [0.307, 0.411] | 0.696 [0.640, 0.746] | 0.320 [0.279, 0.360] |
| frozen graph (step 0) | 0.354 [0.298, 0.404] | 0.451 [0.395, 0.505] | 0.411 [0.360, 0.461] | 0.734 [0.683, 0.781] | 0.402 [0.358, 0.443] |
| full replay | 0.370 [0.314, 0.423] | 0.483 [0.423, 0.533] | 0.445 [0.392, 0.502] | 0.762 [0.712, 0.809] | 0.430 [0.385, 0.475] |

Learned minus dense, paired over the same 319 issues:

| metric | gap |
|---|---:|
| fn Acc@5 | +0.078 [0.047, 0.113] |
| fn Acc@10 | +0.110 [0.075, 0.144] |
| file Acc@1 | +0.088 [0.053, 0.125] |
| file Acc@5 | +0.066 [0.034, 0.097] |
| MRR | +0.106 [0.074, 0.137] |

Every one of those intervals is above 0. Most of that gap is already present at step 0. The paired difference between the full replay and the frozen graph is smaller, and it is the part that training moved:

| metric | full minus frozen |
|---|---:|
| fn Acc@5 | +0.016 [-0.009, 0.041] |
| fn Acc@10 | +0.031 [0.009, 0.056] |
| file Acc@1 | +0.034 [0.013, 0.060] |
| file Acc@5 | +0.028 [0.013, 0.047] |
| MRR | +0.026 [0.005, 0.048] |

Function Acc@10, file Acc@1, file Acc@5, and MRR stay above 0. Function Acc@5 includes 0.

The full holdout curve, 15 steps:

| step | fn Acc@10 | MRR |
|---:|---:|---:|
| 0 | 0.451 | 0.402 |
| 92 | 0.448 | 0.405 |
| 183 | 0.445 | 0.410 |
| 274 | 0.448 | 0.409 |
| 366 | 0.448 | 0.406 |
| 458 | 0.451 | 0.403 |
| 549 | 0.458 | 0.410 |
| 640 | 0.461 | 0.408 |
| 732 | 0.461 | 0.408 |
| 824 | 0.461 | 0.412 |
| 915 | 0.464 | 0.414 |
| 1006 | 0.464 | 0.415 |
| 1098 | 0.467 | 0.412 |
| 1190 | 0.483 | 0.424 |
| 1281 | 0.483 | 0.430 |

The line sits on the frozen score until about step 500, then climbs. Final ablation scores on the same holdout:

| line | fn Acc@10 | MRR |
|---|---:|---:|
| learning off | 0.451 | 0.402 |
| reweight | 0.480 | 0.422 |
| +shortcuts | 0.483 | 0.430 |
| +gap | 0.483 | 0.430 |
| full | 0.483 | 0.430 |

Storing fixes and reweighting edges does almost all of the lift past step 0. Shortcuts add a little MRR. Gap ingestion fired 1667 times and merge/split 33 times, and neither moved the final holdout number past the shortcut line (gap MRR is 0.4300 versus 0.4296 for shortcuts). The full replay wrote 2414 `FIXED_IN` edges and 275 `SHORTCUT` edges. Credit or debit touched 3407 edges. A holdout path looks like `issue #35690 sim 0.74 -FIXED_IN-> QuerySet.in_bulk`.

Prequential Acc@10 does not trend up. The first 100 training issues score 0.460 and the last 100 score 0.460. Prequential MRR does move, from 0.383 on the first 100 to 0.426 on the last 100. The rolling window of 100 is noisy around that mean, which is why the holdout curve is the cleaner picture on this split. Both series are in `results/curve.png`.

## Locate

`run_eval.py --replay` writes the learned edges and the fix memory to `data/learned_state.npz` (gitignored). The MCP server reads that file plus `data/corpus.json` and `data/embeddings.npz`. It does not call an LLM.

```bash
python scripts/mcp_server.py
python scripts/mcp_server.py --http
python scripts/serve_locate.py 8765
```

`scripts/mcp_server.py` is a Python MCP SDK server (`mcp.server.mcpserver.MCPServer`). With no flags it speaks stdio. `--http` serves streamable HTTP at `http://127.0.0.1:8765/mcp`. Do not run that and `serve_locate.py` on port 8765 at the same time.

Tools:

- `locate_bug(report, k)` returns ranked functions with file, line, qualname, score, and the provenance path.
- `learn_from_fix(report, diff)` maps the unified diff onto functions, predicts first, then stores the fix and writes the learned state back. A later `locate_bug` sees that update.

Cursor (`.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "repocortex": {
      "command": ".venv/bin/python",
      "args": ["scripts/mcp_server.py"]
    }
  }
}
```

Claude Code (`~/.claude.json` or the project's `.mcp.json`):

```json
{
  "mcpServers": {
    "repocortex": {
      "command": ".venv/bin/python",
      "args": ["scripts/mcp_server.py"]
    }
  }
}
```

For the HTTP transport, point either client at the URL instead of a command:

```json
{
  "mcpServers": {
    "repocortex": {
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

`serve_locate.py` is the older plain HTTP front (`POST /locate`, `GET /health`). A 20 second Locust run against it, from before this wider graph, made 1251 requests, 0 failures, median 21 ms, about 63 requests per second. That summary is `results/loadtest.json`. It was not rerun on the larger graph.

## Agent eval

`results/agent_eval/PLAN.md` is the plan for comparing an agent that can call `locate_bug` with the same agent that only sees the bug report. The harness is `scripts/agent_eval.py`. This environment has no Claude key, so the model was not called.

```bash
python scripts/agent_eval.py prepare --n 30
python scripts/agent_eval.py score --predictions results/agent_eval/predictions-with-mcp.json
ANTHROPIC_API_KEY=... python scripts/agent_eval.py run --condition without-mcp
ANTHROPIC_API_KEY=... python scripts/agent_eval.py run --condition with-mcp
```

`prepare` writes `results/agent_eval/tasks.json` from the oldest held-out issues. The prompt does not include the gold functions. `run` calls the Anthropic Messages API. `with-mcp` executes `locate_bug` locally and sends the hits back. `without-mcp` has no tool. `ANTHROPIC_MODEL` overrides the default `claude-sonnet-4-5`. If the key is missing, `run` prints these commands and exits without calling a model.

`score` maps the returned names onto the corpus and uses the same strict metrics, including a 95% bootstrap interval.

## Tests

```bash
python -m unittest discover -s tests
```

## What is left

The Next.js dashboard is still a placeholder. It is meant to read `results/baselines.json`, `results/curve.json`, `results/curve.png`, `results/graph.json`, and `results/snapshots.json`. The agent comparison has not been run here.
