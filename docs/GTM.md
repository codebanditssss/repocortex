# Go to market

## Who it is for

Engineering teams that already run coding agents (Cursor, Claude Code, Codex, Devin, in-house agents) on a large codebase with years of history. The pain is sharpest where the repo is big, old, and has a long tail of bug tickets: platform teams, fintech and enterprise backends, open-source maintainers with busy trackers.

The buyer is the engineering lead or platform team that pays the agent bill. The user is the agent, and the developer who reviews what it changes.

## The wedge

One question every bug ticket starts with: where do I edit? Today an agent answers it by searching from zero. RepoCortex answers it from the repo's own fix history, shows why, and can learn from explicitly confirmed fixes. It is narrow enough to measure (did the right function show up first, how many tokens did the agent spend) and it sits in front of every bug-fix task.

What we can already show on Django:

- strict function Acc@10: 41.7% dense + BM25 without graph, 45.1% frozen graph, 48.3% after learning on 319 chronological fix-commit holdout rows; +3.4 percentage points from the structural graph, then +3.1 from learning
- 16 to 27 percent fewer agent input tokens on 30 bugs
- 120/120 valid live responses for distinct held-out reports at four concurrent clients; 3.51s p50 and 4.07s p95 including network and queueing, over 113 seconds. This short read-only test is not a capacity guarantee. [Evidence](../results/service_reliability_120.json)

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

## A pilot a platform lead can evaluate

Use the [maintainer trial instructions and feedback sheet](maintainer-pilot.md) to collect actual observations. No customer adoption or willingness to pay is claimed.

Start with one mature Python backend and the developers who already investigate its bugs. The initial offer is a self-hosted evaluation of that repository's history using the open-source tools available today. The GitHub app, managed plans and enterprise features above are proposals, not services currently sold.

1. Agree on the evaluation before running it: reserve later fixes as a holdout, group repeated tickets together, and compare dense + BM25, the frozen graph and learning on the same reports. Keep a separate development slice for configuration choices.
2. Connect the local MCP server and inspect five representative reports. Check that candidate paths and lines refer to the indexed snapshot, that the service reports its live or replay mode, and that the returned graph queries explain the ranking workflow. See the [setup instructions](../README.md#use-it-from-your-agent).
3. Run the same coding agent with and without `locate_bug` on the reserved tasks. Record input tokens, tool calls, wall time and correctness separately. Count failed searches and setup costs too; fewer tokens alone do not prove cheaper completed fixes.
4. Try confirmed-fix feedback in a separate namespace. Restart the MCP process and check that the feedback is restored without changing the benchmark runtime. Use one writer for that namespace.
5. Continue only if the team's predefined success criteria are met. If learning does not beat the frozen graph, retain that result and investigate before enabling it for everyday use.

The Django curve's early dip, the flat Flask pilot and the one-report HTTPX gain make repository-specific evaluation essential. The roughly 500-fix crossover observed on Django is not a minimum-history guarantee for another codebase. Setup also requires local corpus and embedding artifacts; this is not a one-click import of arbitrary repositories.

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
