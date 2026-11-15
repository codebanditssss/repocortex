# Go to market

## Who it is for

Engineering teams that already run coding agents (Cursor, Claude Code, Codex, Devin, in-house agents) on a large codebase with years of history. The pain is sharpest where the repo is big, old, and has a long tail of bug tickets: platform teams, fintech and enterprise backends, open-source maintainers with busy trackers.

The buyer is the engineering lead or platform team that pays the agent bill. The user is the agent, and the developer who reviews what it changes.

## The wedge

One question every bug ticket starts with: where do I edit? Today an agent answers it by searching from zero. RepoCortex answers it from the repo's own fix history, shows why, and can learn from explicitly confirmed fixes. It is narrow enough to measure (did the right function show up first, how many tokens did the agent spend) and it sits in front of every bug-fix task.

What we can already show on Django:

- strict function Acc@10: 41.7% dense + BM25 without graph, 45.1% frozen graph, 48.3% after learning on 319 chronological fix-commit holdout rows; +3.4 percentage points from the structural graph, then +3.1 from learning
- 16 to 27 percent fewer agent input tokens on 30 bugs
- 12/12 valid hosted searches at three concurrent clients; 2.58s p50 and 3.86s p95 including network and queueing. This is a small smoke check, not a capacity guarantee. [Evidence](../results/hosted_search_check.json)

This is a retrospective evaluation on a fixed Django snapshot that includes later fixes. Three test rows share tickets with training; excluding them leaves 316 rows and preserves the learning gain (45.6% to 48.7%). See the [evaluation audit](evaluation-audit.md).

## Distribution

- **MCP first.** It is a local MCP server with three tools: locate_bug, learn_from_fix and graph_status. Listing in MCP directories and the Cursor and Claude Code MCP setup docs gets it in front of agent users with no integration work.
- **GitHub app next.** Ingest on merge from a webhook, so `learn_from_fix` runs on every merged PR without anyone calling it.
- **Open-source core.** The graph builder, rankers, and operators stay open so teams can verify the eval on their own repo before paying.

## Self-hosted by default

Private code is the first objection. RepoCortex runs on self-hosted HydraDB 0.4.0 in Docker, and the ranker makes no LLM calls, so ranking does not send code to an LLM provider. Initial setup downloads public embedding weights. Runtime corpus, embeddings and learned-state files must be managed alongside HydraDB. HydraDB Cloud is a config change for teams that want it managed.

## Pricing idea

- Free: open source, one repo, self-hosted.
- Team: per indexed repo per month, includes the GitHub app, ingest on merge, and a dashboard of accuracy and tokens saved.
- Enterprise: multi-repo graphs, SSO, on-prem support, and an eval on the customer's own history before purchase.

The initial pilot measures input tokens per investigation and whether all changed functions appear in the suggested context. It does not yet establish fewer dollars per resolved ticket, faster completed fixes, or higher agent accuracy. Pricing and demand remain hypotheses, not validated customer traction.

## Competition

| | what it does | what RepoCortex adds |
|---|---|---|
| Vector code search (embeddings over chunks) | Finds text that looks like the report | Adds relations and fix history. The stronger dense + BM25 control scores 41.7%, frozen graph 45.1%, learned graph 48.3% on this replay |
| Static code graphs and repo maps | What calls what, at one point in time | Learns from fix history; measured +3.1 points over the frozen graph on Django |
| Agent-native search (grep and read loops) | Works, but starts from zero every task | A ranked, explained starting point. 27% fewer input tokens when called first |
| Research localizers (LocAgent, SWE-bench tools) | Localize code for agent tasks | Self-hosted MCP workflow with explicit fix feedback; no head-to-head evaluation claimed |

## Metrics to track

- Top-1 and top-10 function hit rate on each customer's own held-out history
- Agent input tokens and tool calls per bug, with and without RepoCortex
- Share of agent sessions that call `locate_bug` first
- Learning lift: hit rate now vs at install
- p95 latency per call
- Repos indexed and fixes learned per week
