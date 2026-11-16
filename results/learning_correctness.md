# Learning correctness review

Two independent worker reviews found four reproducible defects. Fixes are committed in `e5dde45` and `e96a321`.

- Refined shortcut children now receive success credit when their supporting edge reaches the confirmed function. The same pair is credited only once.
- Direct local feedback now reuses its learning operators, preserving progress across calls before a shortcut reaches its creation threshold.
- Every structurally boosted result retains its strongest supporting edge and actual explanation. Previously, a 40-recipient display cap also suppressed learning credit.
- Incoming CALLS traversals now display the stored edge direction correctly.

The structural fix preserves numeric ranking scores and the existing strongest-edge policy. It does not add credit to every contributing edge. Tests cover cached and live graph adapters, more than 40 recipients, high text-score candidates, edge direction, exact float32 scores and ordering, refined-child success, duplicate feedback and per-ranker isolation.

Validation: **310 tests and 72 subtests passed** after both changes. Production runtime was not retrained. Local snapshots still cannot recover subthreshold counters that were never saved; durable restart learning uses the feedback journal.

## What this means for repair evidence

Droid reconstructed all four earlier learned-versus-frozen lookup payloads exactly from saved study inputs. The failed HTTPX #2660 case had no query-active learned score changes across its 440 candidates. HTTPX #2810 reordered the same top-five members; both arms repaired it. None of these defects has been established as the cause of the prior repair outcomes.

The existing result remains **1/2 repairs in each arm**, with more learned-arm tokens on both tasks. Correctness improvements are not evidence of improved repair accuracy. The next separately registered comparison must retain all outcomes and report query-active learning, including zero-signal cases.
