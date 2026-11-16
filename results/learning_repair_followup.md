# Learned-history versus frozen-history repair follow-up

**Hidden regression and guard tests passed: frozen 1/2, learned 1/2. Within the registered budget: frozen 1/2, learned 1/2.**

This is a completed four-attempt exploratory comparison on two previously explored tasks. It does not establish a general learning advantage. The [original pilot](repair_pilot.md) and [frozen-tool follow-up](repair_followup.md) remain unchanged. This trial changes the model from the earlier pilots, so cross-pilot improvements cannot be attributed to learning.

| Task | Arm | Hidden tests | Within budget | Calls | Input / output tokens | Agent time |
|---|---|---|---|---:|---:|---:|
| httpx-2810 | frozen | pass | yes | 5 | 26,165 / 718 | 51.0s |
| httpx-2810 | learned | pass | yes | 6 | 33,280 / 1,025 | 61.0s |
| httpx-2660 | learned | fail | yes | 12 | 140,486 / 3,560 | 192.1s |
| httpx-2660 | frozen | fail | yes | 10 | 86,625 / 2,585 | 162.2s |

Learning produced no repair-success gain in this trial. Both #2660 patches left three hidden regression failures while all guards passed. The learned arm used more calls and tokens on both tasks; one attempt per arm cannot establish a general efficiency effect.

## What differed

Both arms had the same model (`openai/gpt-5.6-luna` through GMI), source snapshot, prompts, tools, default ranking parameters, mandatory initial lookup and optional further lookup. Only learned historical state differed. Frozen memory was empty. The learned graph replayed **50** earlier fixes for #2810 and **43** for #2660 through the existing full learning operators; no task outcome was used for training or tuning.

- httpx-2810: replay added 139 edges and modified 47 existing edges. Initial top-five order changed; full lookup results differed. Memory vectors were independently reconstructed from the recorded training descriptions.
- httpx-2660: replay added 126 edges and modified 39 existing edges. Initial top-five order stayed the same; full lookup results were identical. Memory vectors were independently reconstructed from the recorded training descriptions.

For #2810, learning moved `ASGITransport.handle_async_request` from fifth to second in the initial lookup, but both arms repaired the task. The #2660 initial results were identical despite changed graph state. These graph changes show the treatment was applied. They do not by themselves show that learning improved repairs. With one attempt per arm and two tasks, token/time differences are descriptive only.

## Historical data and leakage controls

Training text came from immutable ancestor fix-commit descriptions, **not** current GitHub issue bodies. Every fix was an ancestor with a commit timestamp strictly before its task base. Diff labels mapped only to functions present in that base. Target issue IDs and both target patch IDs were excluded, including the older target patch from the later task history. Exact patch/text/reference duplicates and near-duplicate descriptions (word-token Jaccard at least 0.8) were removed. The initial eligible counts of 51 and 44 became 50 and 43 after one additional text duplicate per history. No target-description near duplicates were retained.

Complete frozen and learned graph states, training hashes, prompts, budgets, collector, transport and validator hashes were registered before repair calls. The imported package-source archive was captured after the first model turn and is explicitly supplemental rather than backdated. Both rankers lived in one process; production HydraDB and saved production runtime were untouched.

Historical source archives contained no git history. Agents could edit product Python files only. Independent evaluator copies applied hidden regression patches and ran both regressions and guards before/after each attempt. Supplemental auditing checked protected files against the original git archives, matching prompt hashes and tools across arms, nonnegative known token counts, memory vectors and graph changes. The initial lookup query comes from the same hashed collector code and shared prompt; lookup arguments were not separately serialized.

## Fixed execution limits and retained evidence

Four attempts, counterbalanced as #2810 frozen/learned then #2660 learned/frozen; no retries, exclusions or budget extensions. Equal ceilings: 24 model calls, 600 seconds including evaluation, 200,000 input tokens, 48,000 output tokens and 4,096 output tokens per request. Input totals are observed after provider responses; any overshoot is retained and disqualifies budget compliance. Mandatory lookup time and context are included.

A separately recorded preflight found the catalog-listed Qwen coder model deprecated; it was never used for repair attempts. The selected model passed a two-request tool-continuation smoke before registration. All preflight failures remain in the evidence. Registered integrity validation passed for all four attempts. Six supplemental negative integrity tests passed, including rejection of future timestamps, altered descriptions, duplicate history, target references and invalid artifact paths/hashes.

Two hand-selected tasks previously explored during development cannot serve as an independent held-out benchmark. Commit descriptions are a proxy for historical user reports; public-fix memorization by the model cannot be excluded. This report neither erases earlier failures nor supports general repair, token or latency savings.
