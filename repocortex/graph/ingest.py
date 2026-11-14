"""Write a Graph into HydraDB and read it back."""

from __future__ import annotations

from collections import defaultdict

from repocortex.graph.model import Graph
from repocortex.hydradb.base import LABELS, REL_TYPES


# Smoke nodes written by scripts/smoke_hydradb.py. Clear them before a real load
# so their integer ids and edges do not leak into counts.
SMOKE_IDS = [1, 2, 3, 10, 11]


def ingest(client, graph: Graph) -> dict:
    if hasattr(client, "delete_ids"):
        client.delete_ids(SMOKE_IDS)
    by_label: dict[str, list[dict]] = defaultdict(list)
    for node in graph.nodes.values():
        by_label[node.label].append(node.as_row())
    node_counts = {}
    for label in LABELS:
        rows = by_label.get(label, [])
        if rows:
            node_counts[label] = client.upsert_nodes(label, rows)
    by_rel: dict[str, list[dict]] = defaultdict(list)
    for edge in graph.edges.values():
        by_rel[edge.rel].append(edge.as_row())
    edge_counts = {}
    for rel in REL_TYPES:
        rows = by_rel.get(rel, [])
        if rows:
            edge_counts[rel] = client.upsert_edges(rel, rows)
    return {"nodes": node_counts, "edges": edge_counts}


def wipe_graph(client) -> None:
    """Delete every project node so a rebuilt graph does not keep stale ids."""
    for label in LABELS:
        client.query(f"MATCH (n:{label}) DETACH DELETE n")


def clear_learned(client) -> None:
    """Drop shortcut, fix, and issue rows so a replay starts from the code graph."""
    for rel in ("SHORTCUT", "FIXED_IN", "SAME_AS", "REFINES"):
        client.query(f"MATCH (a)-[r:{rel}]->(b) DELETE r")
    client.query("MATCH (n:Issue) DETACH DELETE n")


def load_graph(client) -> tuple[dict, dict, dict]:
    """Return (nodes, edges, truncation flags) read back from HydraDB.

    nodes: uid -> {label, file, name, qualname, doc, signature}
    edges: (src, rel, dst) -> {w, hits, misses, count}
    """
    nodes: dict[str, dict] = {}
    truncated = {"nodes": [], "edges": []}
    for label in ("Repo", "File", "Class", "Function", "Test", "Concept", "Symptom"):
        rows, short = client.fetch_nodes(label)
        if short:
            truncated["nodes"].append(label)
        for row in rows:
            uid = str(row.get("uid") or "")
            if not uid:
                continue
            nodes[uid] = {
                "label": label,
                "file": row.get("file") or "",
                "name": row.get("name") or "",
                "qualname": row.get("qualname") or "",
                "doc": row.get("doc") or "",
                "signature": row.get("signature") or "",
                "start": int(row.get("start") or 0),
                "end": int(row.get("end") or 0),
            }
    edges: dict[tuple[str, str, str], dict] = {}
    for rel in ("CONTAINS", "DEFINES", "CALLS", "IMPORTS", "INHERITS", "TESTED_BY", "CO_CHANGED", "MENTIONS", "RAISES"):
        rows, short = client.fetch_edges(rel)
        if short:
            truncated["edges"].append(rel)
        for row in rows:
            src = str(row["src"])
            dst = str(row["dst"])
            edges[(src, rel, dst)] = {
                "w": float(row.get("w") or 1.0),
                "hits": int(row.get("hits") or 0),
                "misses": int(row.get("misses") or 0),
                "count": int(row.get("count") or 1),
            }
    return nodes, edges, truncated
