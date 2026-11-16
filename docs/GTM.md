# Who RepoCortex serves

RepoCortex helps coding agents find the functions responsible for a bug and
retain what a confirmed fix teaches. The initial customer is a platform or
engineering team running agents on a mature internal backend. The developer
reviews the suggested functions and evidence; the engineering lead decides
whether the saved investigation work justifies operating the service.

## The job

An agent starting a bug investigation needs a useful place to begin. RepoCortex
returns ranked functions, source locations and supporting graph relationships.
A confirmed fix can update the graph so later investigations use that history.
The product claim is deliberately narrow: a better starting point for debugging.
It does not autonomously verify or guarantee a repair.

The current workflow is local or self-hosted:

1. Index a supported source snapshot into an isolated runtime.
2. Restore its graph into a dedicated HydraDB instance.
3. Connect the MCP tools and investigate a report.
4. Review a confirmed fix before recording feedback in a separate namespace.
5. Compare later searches and verify the feedback survives a restart.

Python, Go, TypeScript and JavaScript source indexing is available. Historical
issue-to-fix evaluation currently uses the Python mapper. Supporting a language
at ingestion is not evidence that learning works well on its repositories.
See [repository setup](index-repository.md) and [confirmed-fix feedback](confirmed-fix.md).

## Evidence a buyer can inspect

On the recorded Django evaluation, strict function accuracy@10 is 41.7% for
dense + BM25, 45.1% for the frozen graph and 48.3% after learning, across 319
fix-commit rows. The agent localization study reports 16–27% fewer input tokens
on 30 bugs. These are localization measurements, not completed repair savings.
The fixed source snapshot includes later fixes; three holdout rows share ticket
IDs with training. Excluding those rows preserves the reported learning gain.
See the [evaluation audit](evaluation-audit.md).

The live read-only service check returned 120/120 valid responses at four
concurrent clients, with 3.51s p50 and 4.07s p95 including network and queueing.
That short run is not a capacity guarantee. [Run evidence](../results/service_reliability_120.json).

Transfer is not established by the initial pilots: HTTPX improved by one report,
Flask stayed flat, and training-only memory calibration worsened HTTPX evaluation
results. The production settings were not changed to that candidate.
[Calibration evidence](../results/learning_calibration.md).

## A concrete evaluation offer

Start with one repository and a fixed set of historical bug reports. Agree on
later evaluation cases before tuning. Compare the same agent and model with and
without RepoCortex, using equal budgets and isolated checkouts. Record:

- repairs that pass independent regression and guard tests;
- time, input/output tokens and tool calls for every attempted task;
- setup and indexing cost, failed runs, and missing measurements;
- whether the learned graph improves on frozen graph and plain fix memory.

A team should adopt only if its own results justify the setup and operating
cost. A per-repository support or managed-service subscription is a pricing
hypothesis, not an existing paid plan. We have no independent customer validation
or willingness-to-pay evidence yet. [Pilot instructions](maintainer-pilot.md).

## Deployment and distribution

The current integration is a local MCP server with `locate_bug`, `learn_from_fix`
and `graph_status`. Ranking uses local embedding weights without calling an LLM
provider. Initial setup downloads the public embedding model. Source excerpts,
embeddings and learned state remain sensitive repository data and must be managed
alongside the database.

The public website shows the product and evaluation evidence; it does not onboard
or learn arbitrary private repositories. Automated merge ingestion, managed
hosting plans and enterprise identity features are not currently offered.

Our distinction to demonstrate is function-level localization from real bug
reports, inspectable graph evidence and persistent confirmed-fix feedback. There
is no controlled head-to-head evaluation against other hackathon submissions.
