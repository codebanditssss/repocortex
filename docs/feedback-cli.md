# Search and retain a confirmed fix

Use the local CLI to search, review which functions a diff changes, then store a
confirmed fix for later searches. It uses the same HydraDB journal and learning
functions as the stdio MCP server. No agent client or generation API key is needed.

Complete [local setup](local-setup.md) first: matching recovered runtime files,
installed Python dependencies, the MiniLM model and a connected matching HydraDB
using `HYDRADB_BACKEND=bolt`. The hosted HTTP adapter is refused before connecting
because this workflow requires Bolt traversal and journal support.
A fresh clone alone cannot run searches. For a supplied real Django example that
cleans up after itself, use [the verification command](confirmed-fix.md) instead.

## Search

Save the original bug report as UTF-8 `work/report.txt`. Choose a unique namespace
for this repository and snapshot, and use that same value for every command:

```sh
.venv/bin/python -m scripts.feedback_cli search \
  --namespace django-f24f38c6-my-pilot \
  --report work/report.txt
```

The JSON includes `search.hits` with ranked functions and provenance, live database
query evidence, and `journal.replayed`, the number of retained events loaded by
this process. The CLI requires HydraDB and does not silently fall back to replay.
Search and preview replay existing feedback in memory but do not append events.

## Review a fix before learning it

Save the reviewed unified diff as `work/fix.diff`. Its paths and new-file line
numbers must match the indexed snapshot. The current runtime is Django; supplying
another repository’s diff does not index that repository.

```sh
.venv/bin/python -m scripts.feedback_cli preview \
  --namespace django-f24f38c6-my-pilot \
  --report work/report.txt \
  --diff work/fix.diff
```

Inspect `matched_functions` and compare their file paths and line spans with the
actual reviewed fix. The mapper considers changed lines and returns at most eight
functions; it does not prove that the diff fixes the report, resolve renamed
files, or reconstruct deleted functions from an old snapshot.

Preview does not write feedback. Copy its `review_token` only after checking the
fix and mappings. The token binds the report, diff, namespace, base runtime and
mapped function IDs; it is a confirmation guard, not an authentication secret.

## Apply the reviewed fix

Replace `TOKEN_FROM_PREVIEW` with the token you just reviewed:

```sh
.venv/bin/python -m scripts.feedback_cli apply \
  --namespace django-f24f38c6-my-pilot \
  --report work/report.txt \
  --diff work/fix.diff \
  --review-token TOKEN_FROM_PREVIEW \
  --output work/confirmed-fix-receipt.json
```

The receipt contains `before` and `after` search results, `feedback.learned`
function IDs, and `storage: "hydradb feedback journal"`. An identical report and
diff return a `feedback.skipped` reason instead of adding another event.

Changing the report, diff, namespace or base runtime invalidates the review token.
Preview again rather than bypassing the check. A zero exit status means the
command completed; a nonzero status means it failed.

Unlike the temporary verifier, **apply retains the report and diff in HydraDB**.
It does not overwrite the four runtime files or retrain the embedding model.
Use one writer per namespace; do not run this CLI and a writing MCP process on
that namespace simultaneously.

## Search from a fresh process

Rerun the search command with the same namespace and unchanged runtime. Each CLI
invocation starts a new process and reconstructs learning from the journal.
Inspect `journal.replayed` and compare the returned rankings with the apply
receipt. An improvement on the same report demonstrates feedback behavior, not
held-out accuracy or generalization. You can then search for a different report
in that namespace using another report file.

For agent access, configure `REPOCORTEX_FEEDBACK_NAMESPACE` to the same value in
[local stdio MCP](local-setup.md#3-connect-your-agent), and use it after the CLI
process has exited. The hosted website and HTTP MCP remain read-only.

## Receipt and input handling

Omit `--output` to print JSON to the terminal. When given, it must name a new file
outside `data/`; existing receipts are never overwritten. The file is reserved
before connecting or learning so an invalid output path cannot trigger feedback.
If a command fails, its reserved file can contain `status: "incomplete"`; that is
not a successful receipt. A write can succeed before a later search or receipt
write fails: restart and search the same namespace, or retry the identical
confirmed fix, which is deduplicated by the journal.

Reports must be nonempty UTF-8 text with at most 12,000 characters. Diffs must be
nonempty UTF-8 text with at most 256,000 bytes. Namespaces allow 1–100 letters,
digits, periods, underscores and hyphens. Keep the namespace, base runtime and
HydraDB backup together so future processes can reconstruct the same state.
