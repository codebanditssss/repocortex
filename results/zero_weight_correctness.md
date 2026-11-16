# Zero-weight persistence and retrieval correction

A graph edge with weight `0` was read as weight `1` by several truthiness-based
fallbacks. A zero-weight CALLS edge in a synthetic corpus therefore reappeared
with weight 1 after loading, and could contribute structural retrieval evidence.
Snapshot export could also omit an untouched zero-weight edge or write weight 1.

Edge-weight readers now use their fallback only when the weight is absent or
null. The correction covers corpus loading, snapshots and exports, database
reads and writes, structural traversal, edge updates, learning reports, and
refined-shortcut inheritance. Existing formulas and bounds are unchanged:
notably, FIXED_IN memory weights still have a 0.85 floor. A zero value does not
turn off that memory contribution. Merge inheritance keeps its existing 0.5
fallback, and shortcut compression keeps its existing zero fallback.

Regression tests cover model-free save/load round trips, graph export, adjacency,
reward updates, flushes, checkpoint reporting, live/offline structural evidence,
Bolt rows, the memory floor and refinement inheritance. No embedding model is
downloaded by these tests.

A read-only count of the current runtime on 16 November 2026 found **zero explicit
zero-weight edges** among 138,150 corpus edges and 4,933 learned-state edges. The
runtime files were not modified. This is a correctness fix for accepted graph
values, not evidence of a benchmark or bug-repair improvement; earlier reported
repair results remain unchanged.
