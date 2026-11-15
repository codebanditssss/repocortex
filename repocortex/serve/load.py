"""Rebuild the hybrid ranker from the last replay, without another training pass."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.dense import DenseIndex, Embedder
from repocortex.retrieve.frozen import EdgeTable
from repocortex.retrieve.hybrid import HybridRanker


REQUEST_LOCK_TIMEOUT_SECONDS = 5.0


class RankingBusyError(TimeoutError):
    """The shared ranker did not become available within the queue budget."""


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
    ranker.rebuild_history()
    return ranker


def backend_status(ranker) -> dict:
    """Report whether scoring can ask HydraDB, or is replaying the on-disk graph."""
    client = getattr(ranker, "client", None)
    if client is None:
        return {
            "mode": "replay",
            "connected": False,
            "detail": "no HydraDB client; ranking uses the exported corpus",
        }
    ping = getattr(client, "ping", None)
    if ping is None:
        return {"mode": "replay", "connected": False, "detail": "client has no ping"}
    try:
        info = ping()
    except Exception:
        return {"mode": "error", "connected": False, "detail": "graph connection unavailable"}
    if not info.get("repo") or info.get("functions") != ranker.n:
        return {"mode": "error", "connected": False, "detail": "repository graph is missing or has an unexpected function count"}
    return {
        "mode": "live",
        "connected": True,
        "detail": "Bolt connected",
        "repo": info.get("repo") or "",
    }


def locate_report(ranker, report: str, k: int = 10) -> dict:
    """Use live structural edges when connected; label cached learning separately."""
    if not ranker.request_lock.acquire(timeout=REQUEST_LOCK_TIMEOUT_SECONDS):
        raise RankingBusyError("ranking is busy; try again shortly")
    try:
        status = backend_status(ranker)
        if status.get("mode") == "error":
            raise RuntimeError("live graph health check failed; refusing cached fallback")
        client = ranker.client
        live = bool(status.get("connected") and hasattr(client, "structural_edges"))
        ranker.live_graph = live
        if live:
            client.last_queries = []
            client.trace = True
        try:
            hits = locate(ranker, report, k)
            queries = list(client.last_queries) if live else []
        finally:
            ranker.live_graph = False
            if live:
                client.trace = False
        return {
            "hits": hits,
            "backend": status,
            "queries": queries,
            "source": "live" if live else "replay",
            "scoring": "live structural graph + cached learned memory" if live else "cached graph and learned memory",
        }
    finally:
        ranker.request_lock.release()


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
