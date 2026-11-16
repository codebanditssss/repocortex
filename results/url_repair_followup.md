# Correlated URL specification repair study

Eight scheduled attempts, four per arm: verified evaluator passes **3/4 frozen versus 3/4 learned**; budget-compliant repairs **2/4 versus 2/4**.

The seventh (2694 learned) process was interrupted after 12 durable responses. Its final tests and complete usage are unknown; it was not retried. The eighth, never-started frozen attempt was run once with the original registered harness after hash and pristine-checkout verification. Only three learned attempts have terminal evaluations. Fractions below use all scheduled attempts; an interrupted attempt is not evidence of a failed patch. No complete four-pair superiority claim is supported. Compliant repair requires a completed run, no retained errors, known usage within all budgets, and passing regression plus guard tests. These results describe four related HTTPX URL-parser tasks. They do not establish general improvement. Prompts were explicitly reconstructed by the evaluator from immutable upstream regression tests; original pre-fix issue wording could not be verified. The localization dataset had previously been inspected.

| Task | Arm | Regression + guards | Compliant repair | Calls | Known input/output tokens | Agent seconds | Status |
|---|---|---|---|---:|---:|---:|---|
| httpx-3140 | frozen | 91/91 pass | True | 7 | 55990/1471 | 105.4 | completed |
| httpx-3140 | learned | 91/91 pass | True | 8 | 72809/1357 | 119.8 | completed |
| httpx-2883 | learned | 86/86 pass | False | 17 | 212464/4442 | 293.9 | budget_exceeded |
| httpx-2883 | frozen | 85/86 pass | False | 10 | 108847/2166 | 141.2 | completed |
| httpx-2721 | frozen | 76/76 pass | True | 11 | 151346/3785 | 237.0 | completed |
| httpx-2721 | learned | 76/76 pass | True | 9 | 83467/3173 | 187.9 | completed |
| httpx-2694 | learned | unavailable (interrupted) | False | 12 durable; total unknown | ≥139101/≥6342 (partial) | unknown | harness_error_usage_unknown |
| httpx-2694 | frozen | 35/35 pass | False | 7 | 55848/1927 (lower bound; total unknown) | 201.4 | provider_error |

All scheduled attempts used GMI `openai/gpt-5.6-luna`, identical tools and mandatory initial lookup, with 24 calls, 600 seconds, 200k input and 48k output tokens per arm. Historical learned state was the sole intended treatment. No retries or case replacement. Both original sources and evaluator execution were isolated; evaluator tests were mounted read-only. Independent validation checked frozen hashes, ancestry, tool/query equality, usage, protected files and JUnit results.

| Task | Prior fixes | Qualifying memory events | Memory recipients | Changed scores / ranks | Top-five overlap |
|---|---:|---:|---:|---:|---:|
| httpx-3140 | 54 | 1 | 2 | 7 / 36 | 5/5 |
| httpx-2883 | 50 | 1 | 2 | 40 / 50 | 4/5 |
| httpx-2721 | 48 | 1 | 2 | 6 / 10 | 4/5 |
| httpx-2694 | 46 | 1 | 2 | 6 / 8 | 4/5 |

Training applied gap ingestion, path compression and edge reweighting in every task. Entity merge/split activated zero times in all four; it was not forced on. Operator invocation, actual applied-operation totals and graph deltas are preserved in the JSON/evidence. Query activity was measured only after registration and never used to select tasks or tune parameters.

Historical descriptions came exclusively from strictly earlier ancestor commit messages with target fixes/references, duplicate patches and near-duplicate descriptions excluded. State histories contained 54/50/48/46 events. All package sources were archived before calls.

Earlier evidence remains unchanged: [original pilot](repair_pilot.md), [frozen-tool follow-up](repair_followup.md), and [two-task learned/frozen study](learning_repair_followup.md). Neither reconstruction nor this correlated sample supports a broad unseen-report claim.

Evidence: `outputs/url-repair-study/evidence.zip`; exact protocol and all eight outcomes retained.

Known-token usage estimates $1.028 at the saved uncached rates. This is not the provider invoice; caching can reduce cost. This includes the interrupted attempt’s known 139,101 input / 6,342 output token lower bound, reported separately; in-flight usage and final total remain unknown.

The 2883 learned attempt passed the evaluator but exceeded the input budget (212,464 > 200,000). Its final malformed replace_text call supplied read-file arguments without required old/new strings, producing a retained KeyError. It was not retried.

The 2694 frozen attempt produced a patch passing all 35 evaluator tests, but request 7 timed out. Its request usage is unknown, it did not finish normally, and the repair is not compliant. The reported 55,848 input / 1,927 output tokens are a lower bound from six returned responses. No retry was made.
