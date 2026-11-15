"""Synthetic feedback/persistence mechanism demo; not an accuracy benchmark.

Run: python -m scripts.demo_feedback
Uses a temporary corpus and deterministic vectors, no model download or database.
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.dense import DenseIndex
from repocortex.retrieve.frozen import EdgeTable
from repocortex.retrieve.hybrid import HybridRanker
from repocortex.serve.learn import learn_from_fix
from repocortex.serve.load import load_ranker, locate_report


class FixtureEmbedder:
    """Deliberately equal similarities isolate the feedback memory mechanism."""

    def encode(self, texts):
        return np.tile(np.array([1.0, 0.0], dtype=np.float32), (len(texts), 1))

    def encode_one(self, text):
        return self.encode([text])[0]


def run_demo() -> dict:
    nodes = {
        f"func:fixture.py:{name}": {
            "label": "Function", "name": name, "qualname": name,
            "file": "fixture.py", "signature": "", "doc": "",
            "start": start, "end": start + 3,
        }
        for name, start in [("alpha", 1), ("beta", 10)]
    }
    uids = list(nodes)
    matrix = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    report = "Synthetic regression reproduced"
    diff = "--- a/fixture.py\n+++ b/fixture.py\n@@ -10,1 +10,1 @@\n-old\n+fixed\n"

    def snapshot(ranker):
        result = locate_report(ranker, report, k=2)
        return {
            "source": result["source"],
            "memory_entries": len(ranker.memory),
            "hits": [{key: hit[key] for key in ("rank", "uid", "score", "path")}
                     for hit in result["hits"]],
        }

    with TemporaryDirectory(prefix="repocortex-feedback-demo-") as temp:
        root = Path(temp)
        data = root / "data"
        data.mkdir()
        (data / "corpus.json").write_text(json.dumps({"nodes": nodes, "edges": []}))
        np.savez(data / "embeddings.npz", uids=np.array(uids), matrix=matrix)
        ranker = HybridRanker(nodes, EdgeTable({}), BM25Index.from_nodes(nodes),
                              DenseIndex(uids, matrix), FixtureEmbedder())
        before = snapshot(ranker)
        feedback = learn_from_fix(ranker, report, diff, state_path=data / "learned_state.npz")
        after = snapshot(ranker)
        # Exercise the production loader, replacing only its model dependency.
        with patch("repocortex.serve.load.Embedder", FixtureEmbedder):
            restored = load_ranker(root)
        reloaded = snapshot(restored)
        duplicate = learn_from_fix(restored, report, diff)
        persisted_files = sorted(path.name for path in data.glob("learned_state.*"))
        persisted_edges = len(json.loads((data / "learned_state.json").read_text()))
    return {
        "demo": "synthetic cached feedback mechanism",
        "scope": "Same synthetic report before/after one confirmed synthetic diff; not accuracy or generalization evidence.",
        "database_connected": False,
        "model": "fixed synthetic vectors; no training or model downloads",
        "storage": "isolated temporary directory, removed after reload",
        "report": report,
        "confirmed_diff": diff,
        "before": before,
        "feedback": {"learned": feedback["learned"], "ticket": feedback["ticket"]},
        "saved": {"files": persisted_files, "learned_edges": persisted_edges},
        "after": after,
        "reloaded": reloaded,
        "checks": {
            "confirmed_function_promoted": before["hits"][0]["uid"] != after["hits"][0]["uid"]
                and after["hits"][0]["uid"] in feedback["learned"],
            "reload_preserves_prediction": after == reloaded,
            "duplicate_feedback_skipped": bool(duplicate.get("skipped")),
        },
    }


if __name__ == "__main__":
    output = run_demo()
    print(json.dumps(output, indent=2))
    raise SystemExit(0 if all(output["checks"].values()) else 1)
