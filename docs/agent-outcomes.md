# Agent outcome receipts

`scripts/agent_outcome_eval.py` validates and summarizes paired fix-run receipts.
It does **not** run an agent, apply patches, execute tests, contact a provider, or
independently verify a fix. Every report carries
`"scope": "receipt_validation_not_independent_execution"`.

This is a collection schema and an offline receipt validator, **not an independent
real-world benchmark**. The tests use synthetic receipts only. Existing
`agent_eval` / `agent_bench` localization results, ranked functions, and token
savings are not evidence of completed fixes and are not accepted as fix receipts.
`data_kind: "external"` describes externally collected receipts, not independent
verification or a quality endorsement.

## Run

From the repository root:

```sh
python scripts/agent_outcome_eval.py \
  --manifest /absolute/study/manifest.json \
  --receipts /absolute/study/receipts.json \
  --artifacts /absolute/study/artifacts \
  --out /absolute/study/report.json
```

Omit `--out` to print JSON. An output file must not already exist.

- Exit `0`: every expected task/arm receipt is present and valid. Valid failed
  runs still produce exit `0`; inspect outcomes, not just the exit code.
- Exit `1`: at least one missing/invalid slot or rejected receipt.
- Exit `2`: malformed input, invalid manifest/envelope, or an I/O error.

Commands in receipts are data, never instructions to this script. Diagnostics
use stable codes rather than artifact contents. Reports retain task and experiment
IDs, so use non-sensitive identifiers.

## Version 1 schema example

All object fields shown below are required; unknown fields are rejected.
Identifiers are nonempty strings. Counters are integers, not booleans, from `0`
through `2**53 - 1`; budgets and test counts must be positive. Times are finite,
nonnegative seconds, with positive timeouts and time budgets.

The examples are **synthetic schema illustrations, not measured runs**. Repeated
hex digits are digest-shaped placeholders. Replace them with hashes of the
actual files/configuration; these examples alone are not an executable artifact
bundle. A Git commit is 40 or 64 lowercase hex characters; other digests are
64-character lowercase SHA-256 hex strings.

### Manifest (`manifest.json`)

The manifest fixes one pair of arms per task: `baseline` and `locate`.

```json
{
  "schema_version": 1,
  "experiment_id": "SYNTHETIC-NOT-A-BENCHMARK",
  "data_kind": "synthetic",
  "protocol": {
    "agent": "synthetic-agent-v1",
    "model": "synthetic-model-v1",
    "config_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "environment_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "base_tools": ["shell", "edit"],
    "budget": {
      "elapsed_s": 600,
      "input_tokens": 100000,
      "output_tokens": 10000,
      "model_calls": 100
    },
    "cache_policy": "cold-per-run",
    "locate_snapshot_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  },
  "tasks": [
    {
      "task_id": "SYNTHETIC-1",
      "repository": "synthetic-local-repository",
      "base_commit": "dddddddddddddddddddddddddddddddddddddddd",
      "prompt_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
      "tests": [
        {
          "test_id": "regression",
          "argv": ["python", "-m", "pytest", "tests/test_regression.py", "--junitxml=report.xml"],
          "cwd": ".",
          "timeout_s": 30,
          "test_count": 1,
          "expected_before": "fail"
        }
      ]
    }
  ]
}
```

`data_kind` is `synthetic` or `external`. Task IDs and per-task test IDs must be
unique. Each task needs at least one `expected_before: "fail"` test specification;
additional guard commands can use `"pass"`. Each specification represents one
command and its exact JUnit testcase count. `cwd` is a normalized, relative POSIX
path; `"."` means the checkout root. Tool names in `base_tools` are unique and
exclude `locate_bug`.

### Receipt envelope (`receipts.json`)

This example shows **one baseline receipt only**. On its own it leaves the locate
slot missing, so evaluation exits `1`. Collect a second receipt for `arm: "locate"`
with distinct run/checkout IDs and its own real artifacts; use the same protocol,
task, base commit, and prompt. Its tools are `base_tools` plus `locate_bug`.
Availability does not require use: `locate_bug_calls` may be zero.

```json
{
  "schema_version": 1,
  "receipts": [
    {
      "schema_version": 1,
      "experiment_id": "SYNTHETIC-NOT-A-BENCHMARK",
      "task_id": "SYNTHETIC-1",
      "arm": "baseline",
      "run_id": "synthetic-baseline-1",
      "protocol": {
        "agent": "synthetic-agent-v1",
        "model": "synthetic-model-v1",
        "config_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "environment_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "base_tools": ["shell", "edit"],
        "budget": {
          "elapsed_s": 600,
          "input_tokens": 100000,
          "output_tokens": 10000,
          "model_calls": 100
        },
        "cache_policy": "cold-per-run",
        "locate_snapshot_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
      },
      "checkout": {
        "checkout_id": "synthetic-checkout-baseline-1",
        "repository": "synthetic-local-repository",
        "base_commit": "dddddddddddddddddddddddddddddddddddddddd",
        "clean_start": true,
        "isolated": true
      },
      "prompt_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
      "tools": ["shell", "edit"],
      "locate_bug_calls": 0,
      "status": "completed",
      "elapsed_s": 42,
      "errors": [],
      "transcript": {
        "path": "baseline/transcript.txt",
        "sha256": "4444444444444444444444444444444444444444444444444444444444444444"
      },
      "patch": {
        "path": "baseline/fix.diff",
        "sha256": "5555555555555555555555555555555555555555555555555555555555555555"
      },
      "usage": {
        "path": "baseline/usage.json",
        "sha256": "3333333333333333333333333333333333333333333333333333333333333333"
      },
      "commands": [
        {
          "test_id": "regression",
          "phase": "before",
          "argv": ["python", "-m", "pytest", "tests/test_regression.py", "--junitxml=report.xml"],
          "cwd": ".",
          "timeout_s": 30,
          "elapsed_s": 1,
          "exit_code": 1,
          "timed_out": false,
          "output": {
            "path": "baseline/before.log",
            "sha256": "6666666666666666666666666666666666666666666666666666666666666666"
          },
          "junit": {
            "path": "baseline/before.xml",
            "sha256": "7777777777777777777777777777777777777777777777777777777777777777"
          }
        },
        {
          "test_id": "regression",
          "phase": "after",
          "argv": ["python", "-m", "pytest", "tests/test_regression.py", "--junitxml=report.xml"],
          "cwd": ".",
          "timeout_s": 30,
          "elapsed_s": 1,
          "exit_code": 0,
          "timed_out": false,
          "output": {
            "path": "baseline/after.log",
            "sha256": "8888888888888888888888888888888888888888888888888888888888888888"
          },
          "junit": {
            "path": "baseline/after.xml",
            "sha256": "9999999999999999999999999999999999999999999999999999999999999999"
          }
        }
      ]
    }
  ]
}
```

Artifact references have exactly `path` and `sha256`. Paths are normalized,
relative POSIX paths under `--artifacts`, never absolute, `"."`, or containing
`..` or backslashes. Symlinks resolving outside that root are rejected. Each file,
including manifest and envelope inputs, is limited to 32 MiB. Hashes cover the
exact stored bytes. The transcript must be nonempty. A non-null patch must have
a Git unified-diff header and hunk markers; this is a format check, not proof it
applies, preserves tests, or fixes the bug.

The `protocol` must match the manifest exactly. The baseline cannot use
`locate_bug`. All `before` commands precede all `after` commands. Command `argv`,
`cwd`, and `timeout_s` match the specification exactly, including JSON types.
The sum of command durations cannot exceed the receipt duration (apart from a
1 ms rounding allowance).

`status` is `completed`, `error`, `timeout`, or `budget_exhausted`. Non-completed
runs require an `errors` entry and can have partial or empty `commands` and a
null `patch`. Each error has exactly `kind` and `code`; kinds are `agent`, `tool`,
`provider`, `setup`, `test`, or `other`. Use sanitized codes, not raw exception
text. Record recovered errors too, even on a completed run.

### Usage artifact (`baseline/usage.json`)

```json
{
  "calls": [
    {
      "request_id": "synthetic-request-1",
      "input_uncached": 100,
      "input_cache_read": 20,
      "input_cache_write": 0,
      "output": 30
    }
  ]
}
```

Use one entry per model request, with a unique nonempty `request_id` within the
run. Each token counter is a nonnegative integer or `null` if unavailable.
Normalize provider counters into **disjoint** input categories; do not count
cached tokens twice. `input_total` sums uncached, cache-read, and cache-write
tokens. Any unknown component makes that total unknown, not zero.
`model_calls` is the number of entries. An empty `calls` array represents no
requests, not missing telemetry; completed runs must include at least one call.

### JUnit evidence

Reports must be UTF-8 XML (an optional UTF-8 BOM is accepted). NUL-containing
data, non-UTF-8 encoding declarations, DTDs, and entity declarations are rejected,
including UTF-16/32 encodings that could bypass a raw-byte declaration scan.
Only unnamespaced `testsuite` / `testsuites` roots are supported. Each testcase
needs a name and a unique `(classname, name)` identity. Identities and exact
testcase counts must agree before and after. Suite summary attributes, when
present, must agree with the actual testcase elements.

`failure`, `error`, and `skipped` elements must be direct children of a
`testcase`. A suite-level setup error or a misplaced outcome invalidates the
receipt even if the suite claims zero errors and the command exits zero.
Conflicting testcase outcome kinds are rejected.

A before-phase regression must exit positively with an actual testcase
`failure`, no errors or skips, and no timeout. An already passing test, import
error, crash, or skip does not reproduce the bug. Guard commands must pass
beforehand. After-phase success requires exit zero, no timeout, and every
expected testcase passing. For a timeout, use `timed_out: true` and
`exit_code: null`; otherwise the exit code is an integer. JUnit may be null only
for a timeout or nonzero exit, never to assert a pass. Keep command output even
when no JUnit report was produced.

## Collection protocol

1. **Freeze the study before running.** Choose real fix tasks, base commits,
   exact prompts, regression and guard commands, expected testcase counts, and
   before-phase expectations. Record exclusions and selection rules. Pin the
   agent/model version, configuration, environment/dependencies, tool versions,
   locate snapshot, budgets, and cache policy. Hash the exact saved configuration,
   environment description, snapshot, and prompt bytes using a documented format.
   Do not expose reference patches, fix commits, or post-fix information to either
   arm. Build the locate snapshot from information available at the task baseline.
2. **Create two clean, isolated checkouts per task.** Verify the same repository
   and base commit, with unique checkout and run IDs across all receipts. Do not
   share agent state, edits, or warmed caches unless the frozen cache policy
   explicitly controls that behavior symmetrically. Keep agent/model, prompt,
   base tools, environment, and budgets the same; only the locate arm gets
   `locate_bug`. Randomize or counterbalance arm execution order and record it
   in the collection log. Use separate experiment IDs for repeated trials,
   because version 1 allows only one receipt per task/arm.
3. **Capture the before phase before any edit.** Run every frozen command from
   its declared directory with its timeout. Save separate raw output and UTF-8
   JUnit files immediately so later runs cannot overwrite them. Confirm the
   regression fails by assertion and guards pass. If setup or reproduction
   fails, preserve the attempt as an error receipt, not an unreported exclusion.
4. **Run the fix attempt under the frozen limits.** Measure end-to-end wall time
   with a monotonic clock, from before-phase start through after-phase completion
   or termination. Include model/tool waits and test execution. Enforce limits
   in the collector, log all model requests and locate calls, and retain sanitized
   transcripts, usage, errors, and the final diff. Use `timeout` or
   `budget_exhausted` when stopped; do not relabel interrupted attempts completed.
5. **Capture the after phase without changing the checks.** Run the same test
   commands against the final candidate and save distinct output/JUnit files.
   Audit that the agent did not weaken or replace tests, forge reports, or change
   the test environment. Preserve failures, crashes, missing usage, and partial
   work. Never rerun selectively until a favorable receipt replaces the original.
6. **Seal the artifacts, then validate offline.** Remove secrets and private
   content before storing/sharing, then hash the final bytes and construct
   references. Use pseudonymous request IDs where necessary. Keep an access-
   controlled provenance log connecting receipts to the actual executions.
   Submit both arms for every planned task, including unsuccessful attempts.
   Resolve invalid evidence from original collection records, not by inventing
   success artifacts. Publish missing/invalid counts alongside any comparison.
7. **Separate evidence from claims.** Retain the manifest, receipts, artifact
   hashes, collection procedure, task provenance, exclusions, and audit notes.
   Call results externally collected receipt outcomes, not independently
   reproduced fixes. Independent reproduction requires a separate trusted
   execution and audit; this evaluator does not provide it.

The collector, agent, test runner, provider usage mapping, and artifact provenance
remain trust boundaries. Hashes detect mismatched bytes, not fabricated evidence.
The validator cannot prove checkout isolation, prompt/configuration identity,
snapshot non-leakage, honest elapsed time, complete usage, or test integrity.
Those assertions require collection controls and review.

## Reading the report

- Slots are matched by `(task_id, arm)`, not receipt order. Duplicate slots and
  reused run/checkout IDs invalidate affected receipts instead of overwriting
  them. Unknown tasks/arms are reported as rejected receipts.
- `pass` requires a completed run, matching preflight evidence, all after tests
  passing, a patch, known input/output usage, and compliance with every budget.
  Other completed outcomes are `test_fail`, `no_patch`, and `budget_unverified`.
  Non-completed status values remain failed outcomes. Recovered errors are
  counted even on a passing receipt.
- `pass_rate_all_tasks` keeps every planned task in the denominator.
  `pass_rate_valid_receipts` is conditional on valid receipts; neither missing
  nor invalid evidence is silently treated as a successful run.
- Measurements include valid failed runs. `known_n`, `unknown_n`, and
  `known_total` expose incomplete measurements; `total` and `mean` are null when
  any contributing value is unknown. Empty groups do not fabricate zero totals.
- Pair counts distinguish both-pass, baseline-only, locate-only, and both-fail.
  Deltas are **locate minus baseline** over valid pairs, with both-pass pairs
  reported separately. Negative time/token deltas mean lower locate-arm usage,
  not proof of a causal gain. Report both subsets and their sample sizes.

Run the synthetic schema and regression checks with:

```sh
python -m unittest discover -s tests -p test_agent_outcome_eval.py
```
