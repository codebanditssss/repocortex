# Starlette Track 1 confirmation plan

This confirmation study was fixed before mining or scoring Starlette. It uses
`encode/starlette` at `271c277da0ff64e2048a4d46ecc812b9d61db5f6`, indexes the `starlette`
package, and considers at most 300 merged pull requests with explicit linked
GitHub issues. RepoCortex will report the resulting sample even if it is small
or the result is flat or negative; no second repository will replace it.

The issue and fix stream is ordered by merge time and grouped by fix commit.
Every report in a group is predicted before that fix is learned. A final
protocol registration will freeze the selected cases, source and dataset
hashes, evaluator code, embedding artifact, runtime, parameters, failure rules,
and statistics before the first score is produced.

The causal comparison will give both adaptive arms the same past fixes:

- `flat_memory` stores prior confirmed fixes without graph operators.
- `learned_graph` stores the same fixes and applies edge reweighting, path
  compression, gap ingestion, and entity merge or split operators.

Text-only and frozen-graph arms remain descriptive baselines. The primary
effect is learned graph minus flat memory. A fixed chronological holdout will
be rescored at registered training checkpoints to show whether accuracy rises
as confirmed fixes accumulate. Prequential accuracy is secondary. Reports
sharing one commit count as one cluster for uncertainty.

The study will disclose that GitHub issue bodies can have later edits and that
the final source snapshot can contain later fixes. It is an offline algorithm
evaluation, not evidence that the hosted HydraDB service handled these calls.
