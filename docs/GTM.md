# Go to market

## Who it is for

Engineering teams that already run coding agents (Cursor, Claude Code, Codex, Devin, in-house agents) on a large codebase with years of history. The pain is sharpest where the repo is big, old, and has a long tail of bug tickets: platform teams, fintech and enterprise backends, open-source maintainers with busy trackers.

The buyer is the engineering lead or platform team that pays the agent bill. The user is the agent, and the developer who reviews what it changes.

## The wedge

One question every bug ticket starts with: where do I edit? Today an agent answers it by searching from zero. RepoCortex answers it from the repo's own fix history, shows why, and gets better with every merge. It is narrow enough to measure (did the right function show up first, how many tokens did the agent spend) and it sits in front of every bug-fix task.

What we can already show on Django:

- function Acc@10 0.483 vs 0.373 for a vector store on 319 held-out bugs
- 16 to 27 percent fewer agent input tokens on 30 bugs
- p95 44 ms per call

## Distribution

- **MCP first.** It is an MCP server with two tools. Listing in MCP directories and the Cursor and Claude Code MCP setup docs gets it in front of agent users with no integration work.
- **GitHub app next.** Ingest on merge from a webhook, so `learn_from_fix` runs on every merged PR without anyone calling it.
- **Open-source core.** The graph builder, rankers, and operators stay open so teams can verify the eval on their own repo before paying.

## Self-hosted by default

Private code is the first objection. RepoCortex runs on self-hosted HydraDB 0.4.0 in Docker, and the ranker makes no LLM calls, so nothing leaves the customer's machines. HydraDB Cloud is a config change for teams that want it managed.

## Pricing idea

- Free: open source, one repo, self-hosted.
- Team: per indexed repo per month, includes the GitHub app, ingest on merge, and a dashboard of accuracy and tokens saved.
- Enterprise: multi-repo graphs, SSO, on-prem support, and an eval on the customer's own history before purchase.

The pitch to the buyer is a number they already track: agent spend per resolved ticket.

## Competition

| | what it does | what RepoCortex adds |
|---|---|---|
| Vector code search (embeddings over chunks) | Finds text that looks like the report | Relations: past fixes, co-change, calls, tests. Beats dense by 11.0 points of fn Acc@10 here |
| Static code graphs and repo maps | What calls what, at one point in time | Learns from fix history and keeps improving after every merge |
| Agent-native search (grep and read loops) | Works, but starts from zero every task | A ranked, explained starting point. 27% fewer input tokens when called first |
| Research localizers (LocAgent, SWE-bench tools) | Benchmarks, not a product | MCP server, self-hosted, ingest on merge |

## Metrics to track

- Top-1 and top-10 function hit rate on each customer's own held-out history
- Agent input tokens and tool calls per bug, with and without RepoCortex
- Share of agent sessions that call `locate_bug` first
- Learning lift: hit rate now vs at install
- p95 latency per call
- Repos indexed and fixes learned per week
