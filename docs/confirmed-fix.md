# Verify a confirmed fix

Run one real Django report through search, confirmed-fix feedback and a fresh
process. The command produces a JSON receipt so you can inspect the predictions,
matched functions and persistence checks yourself.

This is a **learning and persistence check**, not a new accuracy benchmark.
The report becomes training feedback during the check, so searching for that
same report afterward cannot establish held-out improvement.

## Before running

Complete steps 1–2 of [local setup](local-setup.md). You need:

- Python 3.11+, installed project dependencies, and the four matching runtime
  files in `data/`.
- The matching `data/dataset.json`, which supplies the original report, upstream
  commit and confirmed function IDs. The serving preflight does not check this file.
- The matching graph restored into a dedicated local HydraDB, with Bolt on
  `localhost`, `127.0.0.1` or `::1`. This verifier refuses remote databases.
- Internet access to fetch the original diff from GitHub and a cached MiniLM model.

If this environment has not loaded MiniLM yet, cache it once:

```sh
.venv/bin/python -c 'from repocortex.retrieve.dense import Embedder; Embedder()'
```

This downloads the retrieval model if needed; it does not retrain it or change
the runtime files. The verification workers use the model cache in offline mode.
No generation API key is needed.

## Run the complete check

From the repository root:

```sh
.venv/bin/python scripts/preflight.py --database
.venv/bin/python -m scripts.verify_real_feedback \
  --ticket 37442 \
  --fetch-diff \
  --output work/feedback-receipt.json
```

Ticket 37442 concerns JSONL deserialization treating Unicode line separators as
record boundaries. The command retrieves the exact diff for the dataset’s
recorded commit and verifies that its changed lines map to the recorded functions.
It then:

1. Searches using the original bug report.
2. Records its confirmed fix in a new, randomly named HydraDB feedback namespace.
3. Searches again and checks that repeating the same feedback is skipped.
4. Starts a fresh process, reconstructs feedback from HydraDB and compares rankings.
5. Removes its temporary feedback records and checks the runtime file hashes and
   database label counts against their starting values.

The temporary namespace is separate from any MCP feedback namespace. Normal
completion removes its records, including on a handled worker failure; a forced
process termination can interrupt cleanup. It never intentionally deletes your
other namespaces or writes the base runtime files.

## Read the result

The terminal summary reports the confirmed function’s ranks before learning,
after learning and after restart, followed by the verification checks. The JSON
receipt contains the full predictions, matched functions, diff provenance,
runtime hashes and individual `checks` results.

A successful run exits with status **0** and all checks pass. A nonzero exit
means setup or verification failed. A receipt with any failed check is evidence
of a failed verification, not a successful run.

Existing receipt files are never overwritten: choose a new `--output` filename
when rerunning. The output must be outside `data/` so it cannot replace a runtime
artifact.

The [recorded run](../results/real_feedback_persistence.json) promoted the confirmed
function from rank 2 to rank 1 and preserved the ranking after process restart.
Those are example results from the recovered runtime, not a guarantee for every
report or different snapshot. The invariant to verify is that the fresh process
restores the same learned ranking and duplicates do not add another event.

For a diff already saved locally, replace `--fetch-diff` with `--diff path/to/fix.diff`.
The verifier still contacts GitHub to check that it matches the dataset commit.
Use `--help` for the available options.

## Keep learning with an agent

This check deliberately cleans up after itself. To retain confirmed fixes, follow
[the local stdio MCP setup](local-setup.md#3-connect-your-agent): choose your own
namespace, call `locate_bug`, review the fix, call `learn_from_fix`, and search
again. Restart with the same namespace and runtime to replay its journal.

The hosted website and HTTP MCP are read-only. A fresh clone without the runtime
cannot run this check, and this Django runtime cannot learn an unrelated
repository merely by receiving its diff.
