# Track 1 evidence checklist

Audit date: 16 November 2026. “Implemented” describes a bounded capability;
“measured” describes the linked experiment. Neither means first place or universal
correctness. This checklist retains negative results and unfinished submission items.

| Category | Completed evidence | What is not established or remains open |
|---|---|---|
| Learning advantage | Django replay curve; four repository comparisons with five arms; frozen fresh datasets, source hashes, per-report outcomes and correlated-fix caveats; actual paired repair attempts with independent regression execution. | Consistent learning transfer is not established. The original repair pilot remains 0/2 per arm. Follow-up hidden tests pass on 1/2 per arm; within budget, baseline is 0/2 and mandatory lookup 1/2. This is frozen assistance, not learning; no general repair advantage is established. |
| Graph contribution | Live structural query receipts; frozen/text/flat-memory/traversal-off controls; confirmed-fix feedback survives restart; isolated repository runtimes and namespaces; live and saved evidence labeled separately. | Click's observed benefit comes from frozen structure, not additional learning. Werkzeug only ties text-only search after learning. Local persistence and parity do not prove arbitrary-repository quality. |
| Security and reliability | Tests cover malformed/oversized requests, timeouts, unavailable backends, feedback guards and repository mismatch; cumulative search budgets; Go documentation parsing corrected; 120-request hosted concurrency check retained. | This is bounded testing, not an exhaustive security audit, sustained-capacity guarantee or uptime claim. Deployment-specific checks must be repeated after relevant changes. |
| Product usability | Named buyer and debugging job; local repository setup and restore instructions; Locate, copy fallback, navigation and help behavior checked; responsive checks at 320, 390, 768 and 1440 pixels; concrete public-search scope. | No independent user validation or willingness-to-pay evidence. Public search is Django-only; private-repository setup is local/self-hosted, not website onboarding. |
| Consistent release | README links recorded results and failures; current screenshots retained; frontend type/lint/tests and isolated production build checked; Vercel frontend and Railway API deployed; short feature/fix commits in public history. | These records do not replace a release-by-release live flow check. Performance scores vary with device/network and are not guaranteed to reach 100. |
| Submission | Public repository and website links; engineering evidence and buyer hypothesis explained together; negative repair results and absent customer validation disclosed. | A 58-second captioned local walkthrough draft is recorded; public upload and the submission link remain pending. Submission-form acceptance and final judging are not verified here. |

## Evidence locations

- Learning: [Django audit](evaluation-audit.md), [repository controls](../results/repository_ablations.md), [failed calibration](../results/learning_calibration.md), [original repair pilot](../results/repair_pilot.md), [registered repair follow-up](../results/repair_followup.md).
- Graph: [confirmed-fix verification](confirmed-fix.md), [real-fix persistence](../results/real_feedback_persistence.json), [fresh database restart and cross-corpus isolation](../results/restart_and_isolation.json), [local parity](../results/serving_parity_full.json), [production parity](../results/production_parity.json).
- Reliability: [120-request live check](../results/service_reliability_120.json), [HTTP boundary tests](../tests/test_http_security.py), [search budgets](../tests/test_search_budget.py), [runtime isolation tests](../tests/test_restore_runtime.py).
- Product: [customer and evaluation offer](GTM.md), [repository indexing](index-repository.md), [dedicated restore](restore-runtime.md), [maintainer trial](maintainer-pilot.md).
- Release and submission: [README and screenshots](../README.md), [submission draft](../SUBMISSION.md), [public source](https://github.com/codebanditssss/repocortex), [website](https://repocortex.vercel.app/).

An unauthenticated HTTP check on the audit date returned 200 for the public
repository, website, Locate page and `/api/status`. That verifies reachability;
it is not a new search-accuracy, repair or load-test result.
