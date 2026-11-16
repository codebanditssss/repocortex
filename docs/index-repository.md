# Index a new Python repository

`scripts/index_repository.py` parses a local Python repository into a RepoCortex
structural graph and text corpus. It writes to a new directory that is kept
separate from the Django benchmark.

It reuses the same parser (`repocortex.graph.builder.build_graph`)
and the same `corpus.json` format as `scripts/build_graph.py`. Unlike that script,
it never touches `data/` or `results/`, never connects to HydraDB or Bolt, and never
loads `.env` files. It reads Python source, so review the selected source scope
before sharing the generated corpus.

> **This does not give you a trained runtime.** The output is a structural index.
> It has no fix history, no learned edges, and no issue memory. Learning requires
> real fix history or confirmed feedback; improvements must be measured separately.
> Learning is not part of this command.

## Usage

```bash
# Check inputs and preview counts without writing anything
python scripts/index_repository.py --repo ~/src/myproject --out ~/rc-indexes/myproject --dry-run

# Write the structural index
python scripts/index_repository.py --repo ~/src/myproject --out ~/rc-indexes/myproject

# Restrict parsing to some directories
python scripts/index_repository.py --repo ~/src/myproject --scope src,tests --out ~/rc-indexes/myproject

# Also compute local dense embeddings (optional, offline only)
python scripts/index_repository.py --repo ~/src/myproject --out ~/rc-indexes/myproject --embed
```

Run `python scripts/index_repository.py --help` to see every flag.
Progress messages go to stderr. Add `--json` to print the manifest on stdout.
The command exits with code 2 on any validation error, and the error message says how to fix it.

## Inputs and safety rules

- **`--repo`** must be a local directory that you trust. Inputs that look like URLs
  (`https://…`, `ssh://…`, `git@host:…`) are rejected, and the command never clones
  or downloads anything. Review a remote repository and clone it yourself first.
  The git commit is read from `.git/HEAD` as plain text. The command never runs `git`,
  so no hooks or repository config are executed.
- **`--out`** must be either a new directory or an existing empty one. Its parent
  directory must already exist. The command rejects an `--out` that:
  - is not empty (it never overwrites);
  - is inside, or contains, the RepoCortex `data/`, `results/`, `repocortex/`,
    `scripts/` or `tests/` directories, or is the project root itself;
  - is inside, or contains, the input repository.
- Output is first written to a hidden staging directory next to `--out`. The staging
  directory is renamed to `--out` only after every step succeeds. If any step fails,
  the staging directory is deleted, so you never get a half-written index.
- **`--scope`** takes relative directories inside the repository. If you omit it, the
  command uses every top-level directory that contains `.py` files, plus any top-level
  `.py` files. Top-level hidden directories, virtualenvs, `build/`, `dist/` and
  `node_modules/` are skipped.
- **Skipped files:**
  - `migrations/` directories (same rule as the builder);
  - vendor and tool directories at any depth (`.venv`, `venv`, `site-packages`,
    `node_modules`, `__pycache__`, `.git`, …);
  - files larger than 2 MB;
  - symlinks that resolve outside the repository.
- `--max-files` (default 20000) stops the run before an unexpectedly large tree is parsed.
  Set it to `0` to disable the limit.
- The parser only reads source with `ast`. It does not import or execute any of the
  indexed code. Still, use this command only on repositories you trust.

## Outputs

```
<out>/
  manifest.json            inputs, git HEAD, counts, skipped/unparseable files, limitations
  data/corpus.json         nodes and edges in the build_graph.py corpus format
  data/embeddings.npz      only with --embed (uids, matrix, model), same format as the benchmark cache
  results/graph_stats.json node counts by label and edge counts by relation
```

`data/corpus.json` can be read with `repocortex.graph.export.load_corpus`.

## Local embeddings (`--embed`)

Embeddings are optional and run as a separate step. Before loading the model, the
command sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. The sentence-transformers
model (default `sentence-transformers/all-MiniLM-L6-v2`, or the one passed with
`--model`) must therefore already be in the local cache. If the model is missing or
`sentence-transformers` is not installed, the run fails with a clear message and
nothing is written. Rerun without `--embed` to get the structural index alone.

## Limitations

- **Not a learned runtime.** `learned_state.json` and `learned_state.npz` are not
  produced, so `repocortex.serve.load.load_ranker` cannot load this directory.
  The output has no SHORTCUT or FIXED_IN edges and no issue memory. Those require
  replaying real fix history or feedback.
- **No co-change signal.** No commit history is mined, so there are no `CO_CHANGED` edges.
- **Static, name-based structure.** CALLS edges are resolved by name. Calls with
  ambiguous targets are dropped, and dynamic dispatch is not modelled.
- **No database writes.** Nothing is ingested into HydraDB or Bolt. To serve or learn
  from this index, ingest it in a separate step that you control.
- **Parse coverage.** Files that this Python version's `ast` module cannot parse are
  skipped. The number skipped is recorded as `files_unparseable` in `manifest.json`.
- **Root node name.** The root is `repo:<checkout-directory-name>`; its graph edges
  use the same identifier. Keep indexes isolated when checkout names coincide.
- **No benchmark results transfer.** Evaluation numbers measured on the Django
  benchmark do not apply to an index built with this command.
