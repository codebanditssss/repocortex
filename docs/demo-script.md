# RepoCortex demo script

About 2 minutes, 1080p. Screen recording of the web app with a voiceover and one caption line per scene. Every number is from `results/`.

## 0:00 to 0:15  Landing page, hero and ticket animation

Caption: RepoCortex: a code graph in HydraDB that learns from every merged fix

Coding agents spend a lot of their tokens just finding where a bug lives. Keyword search and vector stores treat every bug report like the first one they have ever seen. RepoCortex is a code graph in HydraDB that learns from every fix your team merges.

## 0:15 to 0:28  Landing page, slow scroll to the end

Caption: Django: 46,443 nodes, 138,150 edges, 1,281 fixes replayed in time order

We built it on Django. Forty six thousand nodes and a hundred and thirty eight thousand edges: files, functions, tests, calls, and twelve hundred eighty one real fixes, replayed in the order they happened.

## 0:28 to 0:58  /app/replay, Function Acc@10, playhead swept from 0 to 1281

Caption: 319 retrospective fix rows. fn Acc@10: dense + BM25 41.7%, frozen graph 45.1%, learned 48.3%. Three rows share training tickets.

For each fix, the graph guesses first, then sees the real diff and rewires itself. It stores the fix, reweights the edges that led to the right function, and adds shortcuts for paths it keeps walking. On three hundred nineteen later fix commits, dense plus BM25 gets forty two percent. Adding the frozen graph gets forty five; learning gets forty eight. This is a retrospective replay on one snapshot. Three test rows share training tickets; excluding them preserves the gain. The climb is late, and we show it as is.

## 0:58 to 1:13  /app/locate, type 36605, open the full receipt

Caption: Ticket #36605: rank 1 via past fix #35690 and two learned SHORTCUT edges

Every answer comes with a receipt. For ticket three six six oh five, the top hit is QuerySet dot in bulk, reached through a past fix on a similar ticket and two learned shortcut edges. The receipt shows which stored fixes and graph links supported the ranking.

## 1:13 to 1:36  /app/agent, scroll through the with and without panes

Caption: Claude agent, 30 held-out bugs: 16% fewer input tokens, 27% when told to call it first

We gave it to a Claude coding agent over MCP, on thirty held out bugs. The agent used sixteen percent fewer input tokens, and twenty seven percent fewer when told to call RepoCortex first. On its own, locate bug named the right function first forty seven percent of the time. The agent managed forty. That takes under a second, with no model call.

## 1:36 to 1:44  /app/load

Caption: Saved cached phase-2 test: 8 users, 20 s, 63 req/s, p95 44 ms, 0 failures

The smaller cached ranker handled eight concurrent users at forty four milliseconds p95. This is not live database latency.

## 1:44 to 1:58  /app/connect, MCP config

Caption: One MCP config for Cursor or Claude Code. Self-hosted HydraDB.

One MCP config for Cursor or Claude Code, on self hosted HydraDB, so your code stays on your machines. RepoCortex. Every merged fix makes it better at finding the next bug.

## Sources

- Accuracy and intervals: `results/baselines.json`, `results/curve.json`, `results/lexical_gap.json`
- Split, repeated tickets, and sensitivity: `docs/evaluation-audit.md`
- Provenance: `results/provenance.json`
- Agent eval: `results/agent_eval/results.json`, `tool_only.json`
- Load: `results/loadtest.json`
- Graph size: `results/graph_stats.json`
