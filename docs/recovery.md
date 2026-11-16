# Recovering the saved graph

## Download the matching retrieval runtime

The [Django runtime release](https://github.com/codebanditssss/repocortex/releases/tag/runtime-django-f24f38c6)
contains the five data files used by the published experiment, a per-file manifest,
and SHA-256 checksums. It excludes credentials, database storage, and model weights.
The source snapshot is `f24f38c6b2825f15628c07bf2892f1664eed9361`; Django attribution
and its BSD license are included with the release.

From a fresh checkout on Linux, download and verify before extracting:

```sh
mkdir -p work/runtime-download
curl -fL https://github.com/codebanditssss/repocortex/releases/download/runtime-django-f24f38c6/repocortex-django-runtime.tar.gz -o work/runtime-download/repocortex-django-runtime.tar.gz
curl -fL https://github.com/codebanditssss/repocortex/releases/download/runtime-django-f24f38c6/runtime-manifest.json -o work/runtime-download/runtime-manifest.json
curl -fL https://github.com/codebanditssss/repocortex/releases/download/runtime-django-f24f38c6/SHA256SUMS -o work/runtime-download/SHA256SUMS
(cd work/runtime-download && sha256sum -c SHA256SUMS) &&
tar --keep-old-files -xzf work/runtime-download/repocortex-django-runtime.tar.gz
.venv/bin/python scripts/preflight.py
```

Archive SHA-256: `6c240fe0e706b4b4d5ebaf58769dc7e1acbf91d2c9c6fa1739e5c604bb79b747`.
Extraction refuses to overwrite existing files. Use a fresh checkout if your
`data/` already contains a different experiment. On macOS, use `shasum -a 256 -c`
in place of `sha256sum -c`, and `tar -k -xzf` in place of `tar --keep-old-files -xzf`.
This supplies retrieval data; continue below to restore a dedicated HydraDB and
follow [local setup](local-setup.md) for dependencies and the model cache.

## Restore the database graph

`results/graph.json` contains 48,663 nodes and 141,435 relationships from the
learned Django graph. It can restore graph topology, exported weights, hits and
misses. It is not a complete backup of the retrieval runtime: docstrings,
signatures, issue text, embeddings, ordered fix memory and original edge counts
are missing; exported weights have four decimal places.

Validate the export without connecting or writing:

```sh
.venv/bin/python scripts/restore_graph.py
```

Create a **fresh dedicated HydraDB** instance using `docker-compose.yml` and the
local-development setup in README. Point `HYDRADB_BOLT_URI` at that instance.
Then restore:

```sh
.venv/bin/python scripts/restore_graph.py --apply
```

The command refuses existing RepoCortex labels and checks final counts for every
exported label and relationship type. HydraDB 0.4.0 cannot enumerate arbitrary
labels through the queries used here, so this guard does not make a shared
database a safe destination. There is no overwrite/reset option. Imports are
batched and are not transactional; an interrupted import leaves partial data.
Use a new empty dedicated instance to retry. Published result files are never
modified.

## Back up an existing runtime

To make your own matching backup from an existing checkout:

```sh
tar -czf /tmp/repocortex-runtime.tar.gz \
  data/corpus.json data/embeddings.npz \
  data/learned_state.json data/learned_state.npz data/dataset.json
```

The first four files are required for cached serving; `dataset.json` supports
replay. Keep the Django checkout at the recorded snapshot and the Trac cache if
available. Exclude `.env`, credentials and the HydraDB auth-token file. Recovering
source at the same commit can regenerate function text, but cannot recreate the
missing ordered training memory by itself. Recomputed runs must be reported as
new results rather than substituted for the published measurements.
