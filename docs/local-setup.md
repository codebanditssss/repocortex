# Local search and confirmed-fix feedback

To try search immediately, use [hosted Locate](https://repocortex.vercel.app/app/locate).
No installation or model API key is required. The public service is read-only.

This guide runs the recovered Django runtime locally and connects a trusted coding
agent. It does not train a new model or index an arbitrary repository. The four
runtime files must come from the same experiment; a fresh Git clone alone cannot
serve searches.

## 1. Install and check the runtime

From the repository root, with Python 3.11 or newer:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python scripts/preflight.py
```

If the check reports missing files, recover these into `data/` using the
[recovery guide](recovery.md):

```text
corpus.json
embeddings.npz
learned_state.json
learned_state.npz
```

`results/graph.json` restores the database graph but cannot replace these runtime
files. Do not mix artifacts from different snapshots. The preflight checks array
shapes, IDs and fix-memory references without loading the embedding model. It is
not an integrity signature or a complete ranking test. It exits with status 1
when a required check fails.

Retrieval uses local MiniLM embeddings, not a generation API. Initial service
startup may download `sentence-transformers/all-MiniLM-L6-v2`; subsequent starts
can reuse its cache. No Claude, Gemini or Droid key is required.

## 2. Connect the matching HydraDB

Use the database configuration names in `.env.example`. Keep credentials in the
ignored `.env` file or environment variables. To recover the saved graph, follow
[the fresh-instance procedure](recovery.md); do not restore into an existing or
shared database.

```sh
.venv/bin/python scripts/preflight.py --database
```

This performs read-only connection and function-count checks with a 15-second
connection deadline. It suppresses driver diagnostics to keep connection details
out of terminal output. A matching function count is necessary but does not prove
that two databases have identical graph contents.

## 3. Connect your agent

Use local **stdio** for feedback. Replace both absolute paths below with your
checkout location and choose a namespace unique to this repository and snapshot:

```json
{
  "mcpServers": {
    "repocortex": {
      "command": "/absolute/path/hydradb-hack/.venv/bin/python",
      "args": ["/absolute/path/hydradb-hack/scripts/mcp_server.py"],
      "env": {
        "REPOCORTEX_FEEDBACK_NAMESPACE": "django-f24f38c6-my-pilot"
      }
    }
  }
}
```

This is the common `mcpServers` format; use your client's equivalent MCP settings
if it uses a different schema. The server reads `.env` from its repository root,
so the client need not start in that directory. Restart the client after changing
its configuration.

Ask the agent:

> Call graph_status and confirm mode is live. Then call locate_bug with my bug
> report. Show the candidate functions and their evidence before editing code.

`mode: replay` means the answer uses local saved data without live database
reads. It is not a successful live-graph check. A namespaced feedback server
requires a database connection.

## 4. Submit a confirmed fix and check persistence

Use a bug and a unified diff whose changed lines match the indexed code snapshot.
The current runtime indexes Django at `f24f38c6b282`; unrelated code cannot be
learned by supplying its diff to this runtime.

After reviewing the fix, ask the agent to call `learn_from_fix(report, diff)` with
the exact report and confirmed diff. Then call `locate_bug` again. Feedback may
change rankings, but an improvement for the same report is not held-out accuracy.
An identical feedback submission should be skipped as a duplicate.

Restart the MCP process with the **same namespace and unchanged runtime files**,
then repeat the search. The server reconstructs scoring state from its HydraDB
feedback journal. Use one writer per namespace and back up both the database and
runtime files. This does not install an automatic merge webhook.

For read-only HTTP MCP instead, run:

```sh
.venv/bin/python scripts/mcp_server.py --http
```

Connect to `http://127.0.0.1:8765/mcp`. HTTP transport refuses feedback even when a
namespace is configured. Local stdio is the supported write interface.

## Troubleshooting

| Symptom | Action |
|---|---|
| Missing runtime files | Recover all four files from the same experiment; see [recovery](recovery.md). |
| Runtime consistency check fails | Restore matching artifacts. Do not replace individual files with another run's output. |
| Database check fails | Check the database is running, connection settings match, and the graph is restored. Credentials are intentionally not printed. |
| First request is slow | Model loading or the initial MiniLM download may still be running. |
| Feedback requires a namespace | Set `REPOCORTEX_FEEDBACK_NAMESPACE` in the stdio client's environment and restart it. |
| Snapshot fingerprint mismatch | Restore the original base runtime or choose a new namespace; do not reuse a journal with a different snapshot or diff mapper. |
| No function matches a fix | Check the indexed snapshot and diff line numbers. Deleted functions need an old snapshot; the mapper does not guess them. |
| Feedback recovery required | Restart with the same runtime and namespace to replay the committed journal before further requests. |

## Database restart verification

Run `.venv/bin/python -m scripts.verify_database_restart` with Docker and the
locally available HydraDB 0.4.0 image to check recovery in a disposable instance.
It verifies the same ranking after graceful and forced database restarts and
removes its container and storage. [Recorded results](../results/database_restart.json)
cover one synthetic feedback event, not production capacity or immediate
post-commit power-loss durability. It does not connect to your configured database.
