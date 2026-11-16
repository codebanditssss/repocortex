# Index a local repository

`scripts/index_repository.py` parses a local source repository into a RepoCortex
structural graph and text corpus. It writes to a new directory that is kept
separate from the Django benchmark.

It reuses the same parser (`repocortex.graph.builder.build_graph`)
and the same `corpus.json` format as `scripts/build_graph.py`. Unlike that script,
it never touches `data/` or `results/`, never connects to HydraDB or Bolt, and never
loads `.env` files. It reads Python source, so review the selected source scope
before sharing the generated corpus.

> **This does not train a model or graph.** By default the output is a structural index;
> `--embed --runtime` additionally makes it loadable for untrained search.
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

# Prepare an untrained search runtime with empty feedback memory
python scripts/index_repository.py --repo ~/src/myproject --out ~/rc-indexes/myproject --embed --runtime
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
  command uses every top-level directory that contains files matching the selected
  languages, plus matching top-level files (`.py` by default). Top-level hidden directories, virtualenvs, `build/`, `dist/` and
  `node_modules/` are skipped.
- **Skipped files:**
  - `migrations/` directories (same rule as the builder);
  - vendor and tool directories at any depth (`.venv`, `venv`, `site-packages`,
    `node_modules`, `__pycache__`, `.git`, …);
  - files larger than 2 MB;
  - symlinks that resolve outside the repository.
- `--max-files` (default 20000) stops the run before an unexpectedly large tree is parsed.
  Set it to `0` to disable the limit.
- The Python parser reads source with `ast`; optional Go, TypeScript and JavaScript
  parsing uses tree-sitter. Neither imports or executes indexed code. Still, use this command only on repositories you trust.

## Optional Go, TypeScript and JavaScript indexing

Install the optional pinned parser dependencies once:

```sh
.venv/bin/pip install -e '.[multilang]'
```

Then select languages and source-only directories explicitly. For example, from
this RepoCortex checkout:

```sh
.venv/bin/python scripts/index_repository.py \
  --repo /path/to/agent-orchestrator \
  --scope backend/cmd,backend/internal,backend/pkg,frontend/src \
  --languages go typescript javascript \
  --out /tmp/agent-orchestrator-runtime --embed --runtime
```

`python` remains the default. TypeScript includes `.ts` and `.tsx`; JavaScript
includes `.js`, `.jsx`, `.mjs` and `.cjs`. Avoid broad folders containing compiled
bundles, generated clients or copied dependencies; use explicit source scopes.

The optional parser uses tree-sitter without executing the input. It indexes Go
functions and receiver methods, JavaScript/TypeScript function declarations and
methods, named function expressions, and arrow/function expressions assigned to
named variables, object properties or class fields. Named declarations
inside IIFEs and anonymous callbacks are indexed with distinct lexical scope IDs;
anonymous callbacks themselves do not become invented function nodes. File containment,
class definitions and function definitions become structural graph edges.

JavaScript/TypeScript call edges connect unambiguous same-file top-level functions
called through bare identifiers. Go also connects unambiguous named functions
across files in the same directory and declared package. Import-qualified Go
calls resolve only to exported functions in indexed local packages whose exact
import path matches an ancestor `go.mod` module declaration. Explicit import
aliases and nested module boundaries are respected. The manifest records these
module identities; module files are read without running Go or following
`replace` directives. This is static declaration matching, not validation of
`require`, workspace configuration, build tags, or a successful Go build.

Ambiguous targets, shadowed bindings, receiver/member dispatch, external imports,
dot imports, anonymous callbacks and calls inside nested functions remain
unresolved. There is no Go/TypeScript type checker. Existing same-file resolution
is unchanged.
Functions in conventional test files/directories are labeled `Test`, not search
candidates; test discovery is a filename/name heuristic. Files with a tree-sitter
syntax error are skipped completely and included in `files_unparseable`.

This adds parsing coverage. It does not establish fault-localization accuracy or
learning gains for these languages; Django and HTTPX results do not transfer to
this new repository automatically.

## Outputs

```
<out>/
  manifest.json            inputs, git HEAD, counts, skipped/unparseable files, limitations
  data/corpus.json         nodes and edges in the build_graph.py corpus format
  data/embeddings.npz      only with --embed (uids, matrix, model), same format as the benchmark cache
  data/learned_state.json  empty edge list, only with --embed --runtime
  data/learned_state.npz   empty 384-dimensional memory, only with --embed --runtime
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

## Untrained search runtime (`--embed --runtime`)

This option adds the empty state files required by `repocortex.serve.load.load_ranker`.
It requires `--embed` and the default MiniLM model because the serving loader uses
that model for queries. A different `--model` is rejected before source indexing.
The output has zero learned edges and zero stored issue reports. `manifest.json`
records `kind: repocortex-untrained-runtime`, `runtime_ready: true`,
`learned_runtime: false`, and `training_reports: 0`.

The runtime can perform offline structural and lexical/dense search. It has not
been trained, evaluated on this repository, or ingested into HydraDB. Database
restoration and durable confirmed-fix feedback are separate steps. An index with
no non-test functions is rejected in runtime mode.

## Limitations

- **No learned history.** Without `--runtime`, learned-state files are absent and
  the serving loader cannot load the output. With `--runtime`, those files exist
  but start empty. Neither mode creates SHORTCUT/FIXED_IN edges or issue memory;
  those require replaying real fix history or confirmed feedback.
- **No co-change signal.** No commit history is mined, so there are no `CO_CHANGED` edges.
- **Static, name-based structure.** CALLS edges are resolved by name. Calls with
  ambiguous targets are dropped, and dynamic dispatch is not modelled.
- **No database writes.** Nothing is ingested into HydraDB or Bolt. To serve or learn
  from this index, ingest it in a separate step that you control.
- **Parse coverage.** Files that the selected parser cannot parse are skipped.
  The number skipped is recorded as `files_unparseable` in `manifest.json`.
- **Root node name.** The root is `repo:<checkout-directory-name>`; its graph edges
  use the same identifier. Keep indexes isolated when checkout names coincide.
- **No benchmark results transfer.** Evaluation numbers measured on the Django
  benchmark do not apply to an index built with this command.

## Use a separate runtime

Keep each repository in its own runtime directory and dedicated database. Validate
and restore the structural corpus using [the runtime restore command](restore-runtime.md).
Then set `REPOCORTEX_RUNTIME=/absolute/path/to/index` before starting the local MCP
or locate server. Database settings still come from the RepoCortex checkout and
environment, never from the indexed repository.

`python scripts/preflight.py --runtime /absolute/path/to/index --database` checks
that the artifacts and configured database agree. For terminal feedback, pass
`--runtime /absolute/path/to/index` to `scripts/feedback_cli.py` with a separate
namespace. Follow the [search, preview and apply workflow](feedback-cli.md); review
the mapped functions before applying a confirmed fix. New runtimes start with no
learned history.

## Include implementation context

Add `--source-context` to include the first 80 lines (at most 2,000 characters)
of each indexed function in its search document. This lets local dense and
lexical retrieval use behavior described in implementation comments, strings
and identifiers, alongside the function name and signature. Source is read,
never executed. The generated corpus contains these excerpts; keep it private
when the source is private.

This is optional and creates a different runtime fingerprint. Build into a new
directory and use a new feedback namespace. Existing indexes and benchmark
artifacts are unchanged. The added context is not learned fix history, and its
retrieval quality must be measured rather than assumed.
