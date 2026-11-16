# Restore an indexed repository into HydraDB

Use this after [indexing a trusted local repository](index-repository.md).
The runtime directory must contain `data/corpus.json`. It can have a repository
identity such as `repo:my-library`; it does not need to be Django.

Validate the corpus without contacting a database:

```sh
.venv/bin/python -m scripts.restore_runtime --runtime work/my-library-runtime
```

This checks node identities, a single repository root, searchable functions with
valid line spans, supported labels and relationships, dangling or duplicate
edges, and finite weights. The JSON summary reports counts, the repository ID,
and the SHA-256 of the corpus that was read.

## Apply to a dedicated database

Start a **new, empty local HydraDB instance with its own storage**. Do not use the
benchmark database, production service, or a shared database. Configure its Bolt
URI, username, password and database name through the existing `HYDRADB_BOLT_*`
environment variables. Keep credentials out of command history and screenshots.
The CLI reads the project `.env` as defaults; environment variables take priority.

For example, with a dedicated instance already listening on port `27687` and its
authentication configured:

```sh
HYDRADB_BOLT_URI=bolt://127.0.0.1:27687 \
  .venv/bin/python -m scripts.restore_runtime \
  --runtime work/my-library-runtime --apply
```

The example port is not provisioned by this command. `--apply` accepts only local
Bolt endpoints; hosted API and remote endpoints are refused before connecting.

Before writing, the command refuses existing nodes under **every supported
RepoCortex label**, including feedback records. HydraDB cannot enumerate
arbitrary unrelated labels through these restore primitives, so this check does
not make a shared database safe. Only use a fresh dedicated instance, with no
other writer running during restoration.

The importer uses the existing node and edge ingestion functions. It preserves
corpus node descriptions, signatures and source spans, then verifies label and
relationship counts and exact node UID sets. A zero exit status with
`mode: "restored"` means those checks passed. There is no reset, delete, overwrite
or resume option.

If restoration fails after writes begin, the instance may contain a partial
graph. The command does not roll back or delete that data. Inspect the failure
and provision another empty dedicated database before retrying; a rerun against
the partially populated database is refused.

## What this restores

This imports the structural corpus into HydraDB. It does **not** train anything,
import a feedback journal, or put embedding vectors into the database. For search,
keep the matching `data/embeddings.npz` from the indexer alongside the corpus in
the same runtime directory. Point the search/feedback CLI at that runtime and
use this same dedicated database. A freshly indexed repository has no learned
fix history until confirmed feedback is added.
