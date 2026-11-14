"""Second validation pass: gate FIXED_IN so it can only rerank the lexical frontier.

The first pass showed a larger memory weight hurts, because a similar past
issue usually names the wrong function. This pass asks whether that weight
helps once the bonus is limited to functions the report already ranked highly.
Same selection rule as scripts/tune_memory.py. The holdout is not scored.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.tune_memory import BASE, ROOT, _score, accept, _unit
from repocortex.graph.export import load_corpus
from repocortex.learn.replay import replay
from repocortex.mine.dataset import load_dataset
from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.dense import Embedder, build_dense_index
from repocortex.retrieve.frozen import EdgeTable
from repocortex.retrieve.hybrid import HybridRanker, QueryCache

import numpy as np


def main() -> None:
    dataset = load_dataset(ROOT / "data" / "dataset.json")
    train = [issue for issue in dataset["issues"] if issue["split"] == "train"]
    train.sort(key=lambda issue: (int(issue["time"]), int(issue["ticket"])))
    cut = len(train) - max(1, int(round(len(train) * 0.2)))
    fit, val = train[:cut], train[cut:]
    print(f"fit={len(fit)} val={len(val)}", flush=True)
    nodes, edges = load_corpus(ROOT / "data" / "corpus.json")
    bm25 = BM25Index.from_nodes(nodes)
    embedder = Embedder()
    dense = build_dense_index(nodes, embedder, ROOT / "data" / "embeddings.npz")
    state = np.load(ROOT / "data" / "learned_state.npz", allow_pickle=False)
    shared = {int(ticket): _unit(state["vectors"][index]) for index, ticket in enumerate(state["tickets"].tolist())}
    cache = QueryCache()

    def evaluate(params: dict) -> dict:
        fresh = {uid: dict(node) for uid, node in nodes.items()}
        ranker = HybridRanker(fresh, EdgeTable(edges), bm25, dense, embedder, client=None)
        for name, value in params.items():
            setattr(ranker, name, value)
        ranker._vec = shared
        ranker.score_cache = cache
        t0 = time.time()
        played = replay(ranker, fit, val, every=40, mode="full", points=3)
        curve = played["curve"]
        mid, end = curve[len(curve) // 2], curve[-1]
        row = {
            "mode": "full",
            "params": params,
            "step0_acc": curve[0]["function_acc@10"],
            "mid_acc": mid["function_acc@10"],
            "mid_mrr": mid["mrr"],
            "acc": end["function_acc@10"],
            "mrr": end["mrr"],
            "seconds": round(time.time() - t0, 1),
        }
        row["selection_score"] = round(_score(row), 6)
        print(
            f"  score={row['selection_score']:.4f} acc {row['step0_acc']:.3f}->{row['mid_acc']:.3f}->{row['acc']:.3f} "
            f"mrr {row['mid_mrr']:.3f}->{row['mrr']:.3f} frontier={params.get('memory_frontier')} "
            f"lam={params['memory_lam']} agg={params['memory_agg']} ({row['seconds']}s)",
            flush=True,
        )
        return row

    candidates = [
        BASE,
        {**BASE, "memory_frontier": 40},
        {**BASE, "memory_frontier": 40, "memory_lam": 0.20, "memory_agg": "max", "memory_k": 8},
        {**BASE, "memory_frontier": 40, "memory_lam": 0.35, "memory_agg": "max", "memory_k": 8},
        {**BASE, "memory_frontier": 20, "memory_lam": 0.20, "memory_agg": "max", "memory_k": 8},
        {**BASE, "memory_frontier": 80, "memory_lam": 0.20, "memory_agg": "max", "memory_k": 8},
        {**BASE, "memory_frontier": 40, "memory_lam": 0.15, "memory_agg": "sum", "memory_k": 5},
    ]
    rows = [evaluate(params) for params in candidates]
    baseline = rows[0]
    winner = baseline
    for row in rows[1:]:
        if accept(row, winner):
            print("  kept", flush=True)
            winner = row
        else:
            print("  rejected", flush=True)
    path = ROOT / "results" / "tuning.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["frontier"] = [
        {
            "selection_score": row["selection_score"],
            "acc": row["acc"],
            "mrr": row["mrr"],
            "mid_acc": row["mid_acc"],
            "mid_mrr": row["mid_mrr"],
            "params": row["params"],
            "kept": row is winner and row is not baseline,
        }
        for row in rows
    ]
    if winner is not baseline:
        payload["chosen"] = winner["params"]
        payload["chosen_validation"] = {
            "step0_acc": winner["step0_acc"],
            "mid_acc": winner["mid_acc"],
            "mid_mrr": winner["mid_mrr"],
            "acc": winner["acc"],
            "mrr": winner["mrr"],
            "selection_score": winner["selection_score"],
        }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("chose", json.dumps(winner["params"]), flush=True)


if __name__ == "__main__":
    main()
