# RepoCortex submission

Paste-ready answers for the HydraDB Hackathon form. Every number links back to a file in `results/`.

## Project name

RepoCortex

## Tagline

A code graph in HydraDB that gets better at finding bugs every time a fix is merged.

## Track

Track 1: self-improving graph.

## Problem

Coding agents spend a large share of every task just finding where to edit. On a big, old codebase they grep, open files, and read until something looks right, and they start from zero on every bug. The repository already knows a lot about where bugs live: which functions were fixed for similar tickets, which ones change together, what calls what, which tests cover which code. Keyword search and vector stores throw that away. They compare the bug report to each function's text, one at a time, and a report rarely uses the words of the function that fixes it.

## Solution

RepoCortex stores the codebase as a graph in HydraDB: files, classes, functions, tests, concepts, and the `CALLS`, `CO_CHANGED`, `TESTED_BY`, and `DEFINES` edges between them. Given a bug report it seeds from dense and BM25 hits, walks one weighted hop, mixes in the past fixes of similar tickets, and returns ranked functions with the path that got each one there.

Then it learns. When the real fix is merged, it compares its guess with the diff and runs four operators: it stores the fix as a `FIXED_IN` memory edge and reweights the edges that led to the right or wrong answer, writes `SHORTCUT` edges for detours it keeps taking, links missing neighbors when the answer was out of reach, and merges or splits concepts. The changed edges go back to HydraDB.

Agents use it through an MCP server with two tools, `locate_bug` and `learn_from_fix`, from Cursor, Claude Code, or any MCP client.

## How we use HydraDB

- Self-hosted open-source HydraDB 0.4.0 in Docker is the system of record for the graph: 46,443 nodes and 138,150 edges for Django.
- Batch loads with `UNWIND ... MERGE` on our own ids. Reads are paged and checked against `count(*)` so silent truncation would be caught. There was none.
- Every edge carries `w`, `hits`, and `misses`. Learned edges (`FIXED_IN`, `SHORTCUT`, `SAME_AS`, `REFINES`) and new weights are written back with `UNWIND ... MATCH ... SET` during the replay.
- Provenance expansion uses bounded variable-length Cypher paths over `CALLS` and `CO_CHANGED`.
- The same client also speaks the hosted `POST /byog/query` API, so moving to HydraDB Cloud is a config change.

## Why a graph beats a vector store here

Bug location depends on relations, not text: past fixes of similar tickets, co-change history, call paths, and test coverage. On held-out ticket #36865 ("Casting on __exact searches over non-text fields in admin misses indexes"), plain dense search ranks the fixed function `ModelAdmin.get_search_results` #134. RepoCortex ranks it #1 through two earlier fixes of similar tickets and a learned shortcut, and it shows that path. Across all 319 held-out bugs, function Acc@10 is 0.483 for RepoCortex against 0.373 for dense vectors and 0.329 for BM25. The paired gap over dense is +11.0 points, 95% interval [7.5, 14.4].

## Results

Replay of 1281 real Django fixes in commit order, scored on the 319 newest fixes it never trained on.

- Function Acc@10: BM25 0.329, dense 0.373, RepoCortex step 0 0.451, RepoCortex after learning **0.483**.
- Learning lift on the same held-out set: +3.1 points of function Acc@10 [0.9, 5.6], MRR 0.402 to 0.430. The curve is flat for about 500 fixes, then climbs. Storing fixes and reweighting edges do most of it. The ablation is in the README.
- Claude Sonnet 5.5 agent on 30 held-out bugs: 16% fewer input tokens with the tool, 27% fewer and 22% lower cost when told to call it first. Accuracy about the same.
- `locate_bug` alone gets the top-1 function 0.47 of the time, the agent alone 0.40. Under a second, no model call.
- Load test: 1,251 requests, 0 failures, p95 44 ms, 63 requests per second.

Caveats we state up front: one repository, a small agent eval, and most of the gap over dense is already there before learning.

## Demo

- Video (about 2 minutes): VIDEO_LINK
- Live demo: DEMO_LINK
- Screenshots: `docs/img/`

## Repository

https://github.com/codebanditssss/hydradb-hack

## Team

Khushi Diwan ([@laziedev](https://x.com/laziedev), GitHub [codebanditssss](https://github.com/codebanditssss))

## Built with

HydraDB 0.4.0 (self-hosted), Python, sentence-transformers MiniLM, BM25, MCP Python SDK, Next.js, Locust, Claude Sonnet 5.5 for the agent eval.

## 60 second pitch

Coding agents burn a lot of effort on one question: where is the bug? RepoCortex answers it from the repository's own history. It is a code graph in HydraDB that remembers every merged fix, reweights the paths that led to the right function, and adds shortcuts for the ones it keeps taking. On 319 held-out Django bugs it beats a vector store by 11.0 points of function Acc@10, and it keeps improving as fixes land. Every answer comes with its path. Plugged into a Claude agent over MCP, it cut input tokens by 16 to 27 percent. It runs self-hosted, so private code stays private.
