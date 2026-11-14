"""Prove Cypher writes and variable-length traversal against the configured HydraDB."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repocortex.config import Settings
from repocortex.hydradb import connect

SMOKE_IDS = [900001, 900002, 900003]


def main() -> None:
    settings = Settings.load(Path(__file__).resolve().parents[1])
    client = connect(settings)
    print(f"connected backend={settings.backend}")
    try:
        if hasattr(client, "delete_ids"):
            client.delete_ids(SMOKE_IDS)
        client.upsert_nodes(
            "Function",
            [
                {"uid": "smoke:a", "name": "alpha", "kind": "function"},
                {"uid": "smoke:b", "name": "beta", "kind": "function"},
                {"uid": "smoke:c", "name": "gamma", "kind": "function"},
            ],
        )
        # The bolt adapter assigns its own integer ids. Hosted keys on uid.
        if hasattr(client, "uid_to_id"):
            edges = [
                {"src": "smoke:a", "dst": "smoke:b", "w": 1.0, "hits": 0, "misses": 0},
                {"src": "smoke:b", "dst": "smoke:c", "w": 1.0, "hits": 0, "misses": 0},
            ]
        else:
            edges = [
                {"src": "smoke:a", "dst": "smoke:b", "w": 1.0, "hits": 0, "misses": 0},
                {"src": "smoke:b", "dst": "smoke:c", "w": 1.0, "hits": 0, "misses": 0},
            ]
        client.upsert_edges("CALLS", edges)
        client.update_edge_weights("CALLS", [{"src": "smoke:a", "dst": "smoke:b", "w": 2.5, "hits": 1, "misses": 0}])
        if settings.backend == "bolt":
            src = client.uid_to_id["smoke:a"]
            walked = client.query(
                "MATCH (s {id: $id})-[:CALLS*1..3]->(f:Function) "
                "WHERE f.id <> $id RETURN f.uid AS uid",
                {"id": src},
            )
            print("variable-length", [row["uid"] for row in walked.rows], "truncated", walked.truncated)
            if {"smoke:b", "smoke:c"} - {row["uid"] for row in walked.rows}:
                raise SystemExit("variable-length traversal missed a node")
            weight = client.query(
                "MATCH (a {id: $src})-[r:CALLS]->(b {id: $dst}) RETURN r.w AS w, r.hits AS hits",
                {"src": src, "dst": client.uid_to_id["smoke:b"]},
            )
            print("weight", weight.rows)
            if not weight.rows or float(weight.rows[0]["w"]) != 2.5:
                raise SystemExit(f"weight write failed: {weight.rows}")
            expanded = client.expand(["smoke:a"], hops=3, limit=10)
            print("expand", [(hit.uid, hit.path) for hit in expanded.hits])
            if not {hit.uid for hit in expanded.hits} & {"smoke:b", "smoke:c"}:
                raise SystemExit("expand returned no neighbor")
        else:
            expanded = client.expand(["smoke:a"], hops=3, limit=10)
            print("expand", [(hit.uid, hit.path) for hit in expanded.hits], "truncated", expanded.truncated)
        print("smoke-ok")
    finally:
        if settings.backend == "bolt":
            client.delete_ids(list(client.uid_to_id.get(uid) for uid in ("smoke:a", "smoke:b", "smoke:c") if uid in client.uid_to_id))
        else:
            client.delete_uids(["smoke:a", "smoke:b", "smoke:c"])
        client.close()


if __name__ == "__main__":
    main()
