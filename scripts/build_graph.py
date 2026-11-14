"""Parse the snapshot, add train co-change edges, and load HydraDB."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repocortex.config import Settings
from repocortex.graph.builder import add_cochange, build_graph, iter_sources
from repocortex.graph.ingest import SMOKE_IDS, ingest, load_graph, wipe_graph
from repocortex.hydradb import connect
from repocortex.mine.dataset import load_dataset


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    settings = Settings.load(root)
    parser = argparse.ArgumentParser(description="build the code graph and ingest it")
    parser.add_argument("--dataset", type=Path, default=settings.data_dir / "dataset.json")
    parser.add_argument("--reset", action="store_true", help="delete the existing graph before ingest")
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    print(f"building graph from {settings.django_repo} @ {dataset['snapshot'][:12]}")
    graph = build_graph(iter_sources(settings.django_repo, tuple(dataset["scope"])))
    groups = [
        issue["gold_functions"]
        for issue in dataset["issues"]
        if issue["split"] == "train"
    ]
    cochanged = add_cochange(graph, groups)
    print(
        f"nodes={len(graph.nodes)} edges={len(graph.edges)} co_changed_new={cochanged}"
    )
    client = connect(settings)
    try:
        if args.reset:
            print("wiping the existing graph")
            wipe_graph(client)
            client.close()
            client = connect(settings)
        elif hasattr(client, "delete_ids"):
            client.delete_ids(SMOKE_IDS)
        written = ingest(client, graph)
        print("wrote", json.dumps(written))
        nodes, edges, truncated = load_graph(client)
        print(
            f"read back nodes={len(nodes)} edges={len(edges)} truncated={truncated}"
        )
        stats = {
            "snapshot": dataset["snapshot"],
            "backend": settings.backend,
            "local_nodes": len(graph.nodes),
            "local_edges": len(graph.edges),
            "db_nodes": len(nodes),
            "db_edges": len(edges),
            "truncated": truncated,
            "labels": {},
        }
        for node in graph.nodes.values():
            stats["labels"][node.label] = stats["labels"].get(node.label, 0) + 1
        settings.results_dir.mkdir(parents=True, exist_ok=True)
        (settings.results_dir / "graph_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
        # Keep the text the rankers need. The database stores the same fields,
        # and the eval reloads them; this file is the offline corpus backup.
        corpus = {
            "nodes": {uid: node.as_row() | {"label": node.label} for uid, node in graph.nodes.items()},
            "edges": [
                {"src": src, "rel": rel, "dst": dst, "w": edge.w}
                for (src, rel, dst), edge in graph.edges.items()
            ],
        }
        (settings.data_dir / "corpus.json").write_text(json.dumps(corpus), encoding="utf-8")
        print(f"stats -> {settings.results_dir / 'graph_stats.json'}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
