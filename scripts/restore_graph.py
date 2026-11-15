"""Restore the saved graph export into a fresh dedicated HydraDB; validate by default.

This recovers topology and exported weights, not the original text/embedding
corpus or ordered training memory. No published results are changed. Existing
RepoCortex labels are refused; unrelated labels cannot be enumerated by this
engine, so this command must never target a shared database.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repocortex.hydradb.base import LABELS, REL_TYPES


def validate_export(payload: dict) -> dict:
    nodes, edges = payload["nodes"], payload["edges"]
    ids = set()
    labels = Counter()
    relations = Counter()
    keys = set()
    for node in nodes:
        uid = node["id"]
        if not isinstance(uid, str) or not uid or uid in ids:
            raise ValueError(f"Invalid or duplicate node id: {uid!r}")
        if node["label"] not in LABELS:
            raise ValueError(f"Unsupported node label: {node['label']!r}")
        ids.add(uid)
        labels[node["label"]] += 1
    if not ids:
        raise ValueError("Export contains no nodes")
    for edge in edges:
        key = (edge["src"], edge["rel"], edge["dst"])
        if key in keys or key[0] == key[2]:
            raise ValueError(f"Duplicate or self edge: {key}")
        if key[0] not in ids or key[2] not in ids:
            raise ValueError(f"Dangling edge: {key}")
        if key[1] not in REL_TYPES:
            raise ValueError(f"Unsupported relationship: {key[1]!r}")
        if not math.isfinite(float(edge["w"])):
            raise ValueError(f"Non-finite weight: {key}")
        for field in ("hits", "misses"):
            value = edge.get(field, 0)
            if type(value) is not int or value < 0:
                raise ValueError(f"Invalid {field}: {key}")
        keys.add(key)
        relations[key[1]] += 1
    return {"nodes": len(nodes), "edges": len(edges), "labels": dict(labels),
            "relations": dict(relations),
            "limitations": ["Node docstrings/signatures and issue text are absent",
                            "Weights have export precision (four decimals)",
                            "Original edge counts, ticket annotations and split flags are absent",
                            "Embedding vectors and ordered training memory are absent"]}


def restore(client, payload: dict) -> dict:
    summary = validate_export(payload)
    # HydraDB 0.4.0 requires a label for node counts. Refuse any existing
    # project data; the operator must use a fresh, dedicated database, since
    # this dialect cannot enumerate arbitrary labels. No reset is offered.
    if any(client.count_label(label) != 0 for label in LABELS):
        raise ValueError("Restore requires a fresh dedicated database; existing project nodes found, no writes performed")
    nodes = defaultdict(list)
    for source in payload["nodes"]:
        row = {k: v for k, v in source.items() if k not in ("id", "label")}
        row["uid"] = source["id"]
        nodes[source["label"]].append(row)
    for label, batch in nodes.items():
        if client.upsert_nodes(label, batch) != len(batch):
            raise RuntimeError(f"Incomplete node write: {label}")
    edges = defaultdict(list)
    for row in payload["edges"]:
        edges[row["rel"]].append(row)
    for rel, batch in edges.items():
        if client.upsert_edges(rel, batch) != len(batch):
            raise RuntimeError(f"Incomplete edge write: {rel}")
    for label, expected in summary["labels"].items():
        if client.count_label(label) != expected:
            raise RuntimeError(f"Node count verification failed: {label}")
    for rel, expected in summary["relations"].items():
        if client.count_rel(rel) != expected:
            raise RuntimeError(f"Edge count verification failed: {rel}")
    return summary


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, default=root / "results/graph.json")
    parser.add_argument("--apply", action="store_true", help="write to configured freshly created dedicated HydraDB; refuses existing project labels")
    args = parser.parse_args()
    payload = json.loads(args.export.read_text())
    summary = validate_export(payload)
    if args.apply:
        from repocortex.config import Settings
        from repocortex.hydradb import connect
        client = connect(Settings.load(root))
        try:
            summary = restore(client, payload)
        finally:
            client.close()
    print(json.dumps({"mode": "restored" if args.apply else "validation-only", **summary}, indent=2))


if __name__ == "__main__":
    main()
