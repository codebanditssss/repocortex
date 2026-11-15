# Recovering the saved graph

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

For the original cached bug-localization runtime, recover these files from the
original agent's repository directory:

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
