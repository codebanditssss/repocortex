"""Rebuild the hybrid ranker from the last replay, without another training pass."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.dense import DenseIndex, Embedder
from repocortex.retrieve.frozen import EdgeTable
from repocortex.retrieve.hybrid import HybridRanker


def _endpoint(nodes: dict, uid: str) -> None:
    if not uid or uid in nodes:
        return
    kind, _, raw = uid.partition(":")
    label = {
        "concept": "Concept",
        "symptom": "Symptom",
        "issue": "Issue",
        "func": "Function",
        "test": "Test",
        "file": "File",
    }.get(kind, "Concept")
    nodes[uid] = {
        "label": label,
        "name": raw,
        "file": "",
        "qualname": raw if kind == "func" else "",
        "doc": "",
        "signature": "",
    }


def load_ranker(root: Path) -> HybridRanker:
    root = Path(root)
    corpus = json.loads((root / "data" / "corpus.json").read_text(encoding="utf-8"))
    nodes = dict(corpus["nodes"])
    learned_path = root / "data" / "learned_state.json"
    learned = json.loads(learned_path.read_text(encoding="utf-8"))
    edges = {}
    for row in corpus.get("edges") or []:
        edges[(row["src"], row["rel"], row["dst"])] = {
            "w": float(row.get("w") or 1),
            "hits": 0,
            "misses": 0,
            "count": 1,
        }
    for row in learned:
        _endpoint(nodes, row["src"])
        _endpoint(nodes, row["dst"])
        edges[(row["src"], row["rel"], row["dst"])] = {
            "w": float(row.get("w") or 1),
            "hits": int(row.get("hits") or 0),
            "misses": int(row.get("misses") or 0),
            "count": int(row.get("count") or row.get("hits") or 1),
            "learned": 1,
            "tickets": row.get("tickets") or "",
            "split": int(row.get("split") or 0),
        }
    blob = np.load(root / "data" / "embeddings.npz")
    dense = DenseIndex(blob["uids"].tolist(), blob["matrix"])
    embedder = Embedder()
    ranker = HybridRanker(
        nodes,
        EdgeTable(edges),
        BM25Index.from_nodes(nodes),
        dense,
        embedder,
        client=None,
    )
    state = np.load(root / "data" / "learned_state.npz", allow_pickle=False)
    vectors = state["vectors"]
    tickets = state["tickets"].tolist()
    gold_rows = state["golds"].tolist()
    for index, ticket in enumerate(tickets):
        golds = json.loads(gold_rows[index])
        ranker.memory.append(
            {
                "uid": f"issue:{int(ticket)}",
                "ticket": int(ticket),
                "golds": golds,
                "vec": np.asarray(vectors[index], dtype=np.float32),
            }
        )
    ranker._mem_dirty = True
    return ranker


def locate(ranker, report: str, k: int = 10) -> list[dict]:
    k = max(1, min(int(k), 20))
    issue = {
        "ticket": 0,
        "summary": report or "",
        "description": "",
        "gold_functions": [],
        "gold_files": [],
    }
    pred = ranker.predict(issue, k=k)
    hits = []
    for rank, hit in enumerate(pred.hits, start=1):
        node = ranker.nodes.get(hit.uid) or {}
        hits.append(
            {
                "rank": rank,
                "uid": hit.uid,
                "file": hit.file,
                "qualname": node.get("qualname") or node.get("name") or "",
                "line": int(node.get("start") or 0),
                "score": round(float(hit.score), 4),
                "path": hit.path,
            }
        )
    return hits
