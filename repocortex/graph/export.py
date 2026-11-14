"""Write the in-memory graph, including learned edges and weights, as JSON."""

from __future__ import annotations

import json
from pathlib import Path

LEARNED_RELS = {"SHORTCUT", "FIXED_IN", "SAME_AS", "REFINES"}


def dump_graph(nodes: dict, edges, path: Path) -> dict:
    table = edges.edges if hasattr(edges, "edges") else edges
    node_rows = []
    for uid, node in nodes.items():
        node_rows.append(
            {
                "id": uid,
                "label": node.get("label") or "",
                "name": node.get("name") or "",
                "file": node.get("file") or "",
                "qualname": node.get("qualname") or "",
                "start": int(node.get("start") or 0),
                "end": int(node.get("end") or 0),
            }
        )
    edge_rows = []
    for key, props in table.items():
        src, rel, dst = key
        weight = round(float(props.get("w") or 1.0), 4)
        learned = bool(props.get("learned")) or rel in LEARNED_RELS or abs(weight - 1.0) > 1e-6
        row = {"src": src, "dst": dst, "rel": rel, "w": weight}
        hits = int(props.get("hits") or 0)
        misses = int(props.get("misses") or 0)
        if hits:
            row["hits"] = hits
        if misses:
            row["misses"] = misses
        if learned:
            row["learned"] = 1
        edge_rows.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"nodes": node_rows, "edges": edge_rows}, separators=(",", ":")), encoding="utf-8")
    return {"nodes": len(node_rows), "edges": len(edge_rows)}
