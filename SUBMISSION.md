# RepoCortex submission

Paste-ready answers for the HydraDB Hackathon form. Every number links back to a file in `results/`.

## Project name

RepoCortex

## Tagline

Find the functions behind a bug. Learn from the fix—with HydraDB.

## Track

Track 1: self-improving graph.

## Problem

Coding agents need to decide where to investigate before proposing a fix. RepoCortex targets maintainers and platform teams working on mature repositories: it returns candidate functions and inspectable evidence, then retains confirmed-fix history for later reports. Whether that reduces a team's repair effort must be measured; we have no independent customer validation yet.

## Solution

RepoCortex stores the codebase as a graph in HydraDB: files, classes, functions, tests, concepts, and the `CALLS`, `CO_CHANGED`, `TESTED_BY`, and `DEFINES` edges between them. Given a bug report it seeds from dense and BM25 hits, walks one weighted hop, mixes in the past fixes of similar tickets, and returns ranked functions with the path that got each one there.

Then it learns. Historical replay or the `learn_from_fix` tool compares its guess with a confirmed fix diff and runs four operators: it stores the fix as a `FIXED_IN` memory edge and reweights the edges that led to the right or wrong answer, writes `SHORTCUT` edges for detours it keeps taking, links missing neighbors when the answer was out of reach, and merges or splits concepts. Historical replay writes the changed edges back to HydraDB. Live `learn_from_fix` saves confirmed feedback in a namespaced HydraDB journal and reconstructs its scoring updates in memory when the agent restarts.

Agents use it through an MCP server with three tools, `locate_bug`, `learn_from_fix`, and `graph_status`, from Cursor, Claude Code, or any MCP client. Automatic ingestion from merged pull requests is not implemented.

## How we use HydraDB

- Self-hosted open-source HydraDB 0.4.0 in Docker is the system of record for the graph: 46,443 nodes and 138,150 edges initially; the saved learned export has 48,663 nodes and 141,435 edges.
- Batch loads with `UNWIND ... MERGE` on our own ids. Reads are paged and checked against `count(*)` so silent truncation would be caught. There was none.
- Every edge carries `w`, `hits`, and `misses`. Learned edges (`FIXED_IN`, `SHORTCUT`, `SAME_AS`, `REFINES`) and new weights are written back with `UNWIND ... MATCH ... SET` during the replay.
- Live serving reads bounded structural edges from HydraDB and returns query receipts; learned fix memory remains cached. All 319 held-out rows match the offline scorer’s top ten rankings and four-decimal scores on the restored local serving path. A separate eight-query production check matches too. These are serving-parity checks, not new accuracy measurements.
- A real confirmed Django fix is persisted and replayed in a fresh Python process with the same rankings. Repeated submission is idempotent; each feedback namespace is isolated. This demonstrates the learning mechanism, not an additional held-out accuracy gain.
- A hosted `POST /byog/query` adapter also exists. The deployed demo uses the self-hosted Bolt path; hosted-adapter parity is not claimed by these results.

## Why a graph beats a vector store here

Relations add information beyond text: past fixes of similar tickets, co-change history, call paths, and test coverage. On held-out ticket #36865 ("Casting on __exact searches over non-text fields in admin misses indexes"), plain dense search ranks the fixed function `ModelAdmin.get_search_results` #134. RepoCortex ranks that outer function #1 through two earlier fixes of similar tickets and a learned shortcut. The fix also changed the nested helper `construct_search`, which dense retrieval ranks #2. These are recorded results, not a live-query guarantee. Across 319 chronological holdout fix rows, strict function Acc@10 is 0.483 for RepoCortex, 0.451 for the frozen graph, and 0.417 for dense + BM25 without graph. The learned-versus-no-graph gap is +6.58 percentage points, with a paired row-bootstrap 95% interval of [3.76, 9.72]. See the [reproduced comparison](results/lexical_gap.json).

## Results

Retrospective replay of 1,281 Django fix commits in time order, scored on 319 later fix rows using a fixed code snapshot. Three test rows share tickets with training; the set is not 319 unseen issues.

- Function Acc@10: BM25 0.329, dense 0.373, dense + BM25 without graph **0.417**, RepoCortex step 0 0.451, RepoCortex after learning **0.483**.
- Excluding the three rows with train-seen tickets leaves 316 rows: dense + BM25 0.421, frozen graph 0.456, learned graph **0.487**. The learning gain remains +3.16 points [0.63, 5.70], without retraining.
- Learning lift on the same held-out set: +3.1 points of function Acc@10 [0.9, 5.6], MRR 0.402 to 0.430. The held-out curve is flat for about 500 fixes, then climbs: early on, similar past tickets usually name a different function (at step 100 the nearest past fix shares a gold function 3.5% of the time), so memory only pays off once it has enough history. Storing fixes and reweighting edges do most of the lift. The ablation is in the README.
- Two curves that rise earlier, both outside the holdout: on a validation slice of the newest 256 training issues, fn Acc@10 goes 0.414 to 0.449 (peak 0.453) and MRR 0.380 to 0.414. Scoring each training issue before learning from it, the learning graph ends +3.4 points of Acc@10 and +3.3 points of MRR above a frozen replay (0.472 vs 0.439). Over the last 100 issues learning holds 0.460 while frozen falls to 0.410.
- Saved Claude Sonnet 5.5 localization study on 30 held-out bugs: 16% fewer input tokens with the tool, 27% fewer and 22% lower cost when told to call it first. Top-1 correctness was 12/30 without the tool and 13/30 in both tool conditions; this does not establish an accuracy gain.
- In the saved 30-task study, `locate_bug` alone gets the top-1 function 0.47 of the time, the agent alone 0.40. Retrieval makes no generation-model call.
- Hosted search check: 40 requests at four concurrent clients, 40 successful live responses, p50 3.41 s and p95 3.69 s across four repeated reports. This is a small smoke test, not a sustained capacity measurement.
- Saved phase-2 load test: 1,251 requests, 0 failures, p95 44 ms, 63 requests per second. This measured the smaller cached ranker, not live HydraDB traversal latency.

The [evaluation audit](docs/evaluation-audit.md) documents repeated ticket IDs, row-paired bootstrap corrections, and the 316-row sensitivity check. The code snapshot includes later fixes, so this is retrospective localization rather than a historical checkout for each issue. The main learning result is Django. Four additional repository evaluations separate graph structure from learning; none establishes a consistent transfer advantage. There is no controlled head-to-head comparison against other projects.

## Additional evaluations and buyer evidence

[Five-arm repository comparisons](results/repository_ablations.md) use the same questions within each repository: text-only, frozen graph, flat fix memory, learned graph, and learned graph with traversal disabled. HTTPX improves from 14/33 frozen to 15/33 learned; Flask remains 4/7. Click improves over text-only (18/37 to 21/37) through its frozen graph, with no further top-ten learning gain. Werkzeug goes from 8/16 frozen to 9/16 learned, tying text-only search. Click and Werkzeug datasets were frozen before scoring. Source snapshots, hashes, correlated-fix caveats and failures are retained in the report.

An actual [two-task paired repair pilot](results/repair_pilot.md) produced **0/2 repairs in both arms**. No agent produced a patch; one request failed at the provider. These attempts do not establish repair accuracy, time or token savings. They are reported separately from the saved localization study.

The proposed buyer is an engineering team running coding agents on a mature internal backend. The workflow is search, inspect evidence, review a confirmed diff, and retain that feedback in an isolated repository runtime. A paid support or managed-service offer remains a hypothesis, not a validated business. [Customer and evaluation offer](docs/GTM.md)

## Demo

- Video: pending recording and upload; no video is included in this submission draft.
- Website: https://repocortex.vercel.app/
- Live search: https://repocortex.vercel.app/app/locate (Vercel frontend with a Railway-hosted API and HydraDB)
- Screenshots: `docs/img/`
- Recording walkthrough: [demo script](docs/demo-script.md)

## Repository

https://github.com/codebanditssss/repocortex

## Team

Khushi Diwan ([@laziedev](https://x.com/laziedev), GitHub [codebanditssss](https://github.com/codebanditssss))

## Built with

HydraDB 0.4.0 (self-hosted), Python, sentence-transformers MiniLM, BM25, MCP Python SDK, Next.js, Locust, Claude Sonnet 5.5 for the agent eval.

## 60 second pitch

Coding agents burn a lot of effort on one question: where is the bug? RepoCortex answers it from the repository's own history. It is a code graph in HydraDB that remembers confirmed fixes, reweights the paths that led to the right function, and adds shortcuts for the ones it keeps taking. In a retrospective replay on 319 Django fix rows, function Acc@10 rises from 45.1% to 48.3%, against 41.7% for dense + BM25 without graph. Excluding tickets seen in training preserves the gain. Every answer comes with its path. Plugged into a Claude agent over MCP, it cut input tokens by 16 to 27 percent. The graph and retrieval model run self-hosted; code shared with an external coding agent follows that agent's data policy.
