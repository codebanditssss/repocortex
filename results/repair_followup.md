# Paired repair follow-up: frozen graph assistance

Within the registered budget: baseline **0/2**, mandatory initial lookup **1/2**. Ignoring budget compliance, hidden regression and guard tests passed for baseline **1/2** and treatment **1/2**.

This is a two-task exploratory result, not evidence of a general repair advantage. It measures frozen source lookup assistance, **not learning**. The [original failed pilot](repair_pilot.md) remains 0/2 in both arms; its failures were not replaced.

| Task | Arm | Hidden tests | Within budget | Calls | Input / output tokens | Agent time | Stop |
|---|---|---|---|---:|---:|---:|---|
| httpx-2810 | baseline | pass | no | 22 | 208,611 / 8,199 | 96.2s | budget_exhausted |
| httpx-2810 | locate | pass | yes | 17 | 154,773 / 7,100 | 82.8s | completed |
| httpx-2660 | locate | fail | no | 22 | 223,308 / 10,092 | 150.5s | budget_exhausted |
| httpx-2660 | baseline | fail | unknown | 16 | 96,441 / 2,385 + unknown | 66.2s | error |

The final #2660 baseline was retained after provider HTTP 400 `invalid_thinking_signature` (the sanitized response body is in the evidence). No retry followed. Its reported tokens exclude unknown failed-request usage; budget compliance cannot be verified. The #2660 treatment made no edit before exhausting its input budget.

## Registered protocol

Same agent harness and `google/gemini-3.8-flash` provider model in both arms, fresh isolated source archives at the historical parent commits. Equal ceilings: 24 model requests, 600 seconds including evaluation, 200,000 input tokens, 48,000 output tokens, 4,096 output tokens/request. Input usage is observable only after a response; any overshoot is retained and disqualifies budget compliance. No automatic retries. Counterbalanced order: #2810 baseline, #2810 treatment, #2660 treatment, #2660 baseline.

Treatment performs one mandatory initial RepoCortex lookup on the behavioral prompt, then exposes optional further lookups. Baseline has the same read/search/edit/test/finish tools without lookup. Graphs, BM25 and dense index were built only from each exact base source. Learned history and shortcuts were disabled. Mandatory lookup time is included in agent elapsed time and its context in provider input usage.

Agents could edit product Python files only. Hidden upstream regression additions and future fix revisions remained evaluator-only. Before/after regressions and guard suites ran independently in copied checkouts. Historical admission established these tests fail on each parent and pass on the corresponding upstream fix. Source archives omit git history; model pretraining contamination cannot be excluded.

## Smoke and evidence

A provider-only smoke was registered separately and failed with HTTP 403 (`error code: 1010`) before study registration. The transport lacked the User-Agent present in the original collector. After restoring it, a separately retained second smoke passed two tool-continuation calls. Both smoke records predate the trial registration and are excluded from repair outcomes by their registered purpose. No repair attempt was retried or excluded.

The protocol/config, source-snapshot hashes, environment versions, and collector/transport hashes were frozen before the first repair model call. Evidence includes all four transcripts, raw request usage, patches, before/after JUnit results and logs, protocol, smoke records, and test-only patches. Missing provider usage is unknown, never zero. No immutable model version or invoice is available.

The sample is two hand-selected historical tasks with one attempt per arm. Do not infer statistical significance, advertise a general token/latency gain, or claim that learned memory improved repairs. A learning-vs-frozen repair comparison would need separate valid training history and registration.
