# Actual paired repair pilot: no completed repairs

**Result: 0/2 repairs without RepoCortex; 0/2 with the frozen graph tool available.** No agent produced a code patch. These are real failed attempts, not synthetic receipts or localization-only success scores.

| Task | Arm | Outcome | Agent time | Model requests | Reported input / output tokens | Graph calls |
|---|---|---|---:|---:|---:|---:|
| httpx-2810 | baseline | budget_exhausted | 66.6s | 12 | 61,765 / 4,674 | 0 |
| httpx-2810 | locate | completed | 66.5s | 12 | 58,413 / 4,988 | 1 |
| httpx-2660 | locate | error | 28.1s | 11 | 36,122 / 467 + unknown failed-request usage | 0 |
| httpx-2660 | baseline | budget_exhausted | 43.8s | 12 | 44,352 / 1,199 | 0 |

`completed` means the model response loop ended; it does **not** mean a repair passed. The completed locate run made no edits and still failed the regression.

## Independent regression execution

- HTTPX #2810: the two added raw-path assertions fail on the exact parent. Both pass on the upstream fixed revision; all24 ASGI tests pass there. After both agent attempts, the same two regressions still fail and22 guards pass.
- HTTPX #2660: four of11 NO_PROXY parameter cases fail on the exact parent. All54 utility tests pass on the upstream fixed revision. After both agent attempts, the same four regressions still fail and43 guards pass.
- Added tests remained evaluator-only. Agents saw pristine parent exports, ordinary existing tests, and behavioral prompts without target IDs or solution patches. Product edits were the only writable tool operation.

## Protocol and accounting

Same restricted agent harness and model in both arms. Equal ceilings:240 seconds,12 model requests,100,000 input tokens,16,000 output tokens; at most1,400 output tokens per request. Requests ran sequentially with counterbalanced arm order. Both arms had identical file listing, literal search, read, product edit, existing-test and finish tools; only the treatment exposed locate_bug. Both graph snapshots were built from parent source, with no future code or learned fix history.

The collection protocol, prompts, environment versions, snapshot hashes and budgets were frozen before the first model call. The normalizer adds the rejected provider request with unknown token counters from its retained error trace. Four receipts validate; none are missing or invalid. Validator exit0 confirms receipt integrity, not repair success.

Known successful-response cost estimate: $0.1541, based on the saved provider rates. One failed request has unknown usage; actual billing was not available. Do not treat this estimate as an invoice.

## What this establishes

The historical test harness and leakage controls are feasible. This bounded agent configuration did not complete either repair. It does not establish better repair accuracy, token efficiency, latency, or learning gains. Lower treatment elapsed time includes a provider failure and must not be marketed as a speed improvement.

A follow-up needs a newly registered protocol with an agent/model that reliably edits within the budget, complete provider failure diagnostics, and enough tasks for inference. To measure tool use rather than mere availability, specify mandatory initial locate use in advance and report that treatment honestly. Do not silently rerun or drop these failed attempts.

The original four failed attempts are retained. A later harness correction must be reported as a separate study rather than replacing these outcomes.
