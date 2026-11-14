"""Score the held-out split and, with --replay, draw the learning curve."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repocortex.config import Settings
from repocortex.eval.harness import eval_bm25, eval_dense, eval_ranker
from repocortex.eval.plot import plot_curve
from repocortex.graph.ingest import clear_learned, load_graph
from repocortex.hydradb import connect
from repocortex.learn.replay import replay
from repocortex.mine.dataset import load_dataset
from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.dense import Embedder, build_dense_index
from repocortex.retrieve.frozen import EdgeTable, FrozenRanker
from repocortex.retrieve.hybrid import HybridRanker


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    settings = Settings.load(root)
    parser = argparse.ArgumentParser(description="run baselines and the learning curve")
    parser.add_argument("--dataset", type=Path, default=settings.data_dir / "dataset.json")
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--every", type=int, default=40)
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    holdout = [issue for issue in dataset["issues"] if issue["split"] == "test"]
    train = [issue for issue in dataset["issues"] if issue["split"] == "train"]
    print(f"train={len(train)} holdout={len(holdout)}")
    client = connect(settings)
    try:
        nodes, edges, truncated = load_graph(client)
        print(f"graph nodes={len(nodes)} edges={len(edges)} truncated={truncated}")
        if not any(node.get("label") == "Function" for node in nodes.values()):
            raise SystemExit("no functions in the graph; run scripts/build_graph.py")
        bm25 = BM25Index.from_nodes(nodes)
        bm25_metrics = eval_bm25(bm25, nodes, holdout)
        print("bm25", json.dumps(bm25_metrics))
        print("loading sentence-transformers model")
        embedder = Embedder()
        dense = build_dense_index(nodes, embedder, settings.data_dir / "embeddings.npz")
        dense_metrics = eval_dense(dense, embedder, nodes, holdout)
        print("dense", json.dumps(dense_metrics))
        frozen_metrics = eval_ranker(
            FrozenRanker(nodes, EdgeTable(edges), bm25, client, hops=settings.hops),
            holdout,
        )
        print("frozen", json.dumps(frozen_metrics))
        curve = []
        operators = {}
        params = {}
        settings.results_dir.mkdir(parents=True, exist_ok=True)
        if args.replay:
            print("replaying train issues")
            clear_learned(client)
            ranker = HybridRanker(
                nodes,
                EdgeTable(edges),
                bm25,
                dense,
                embedder,
                client,
            )
            played = replay(ranker, train, holdout, every=args.every)
            curve = played["curve"]
            operators = played["operators"]
            params = played["params"]
            print("curve", json.dumps(curve))
            provenance = {
                "holdout": len(played["provenance"]),
                "hits_with_fixed_in": sum(
                    1
                    for issue in played["provenance"]
                    for hit in issue["hits"]
                    if "FIXED_IN" in hit["path"]
                ),
                "hits_with_shortcut": sum(
                    1
                    for issue in played["provenance"]
                    for hit in issue["hits"]
                    if "SHORTCUT" in hit["path"]
                ),
                "issues": played["provenance"],
            }
            (settings.results_dir / "provenance.json").write_text(
                json.dumps(provenance, indent=2), encoding="utf-8"
            )
            ranker.save(settings.data_dir / "learned_state.npz")
            print(
                f"shortcuts={client.count_rel('SHORTCUT')} fixed_in={client.count_rel('FIXED_IN')}"
            )
        payload = {
            "snapshot": dataset["snapshot"],
            "scope": dataset["scope"],
            "backend": settings.backend,
            "hops": settings.hops,
            "train": len(train),
            "holdout": len(holdout),
            "truncated": truncated,
            "baselines": {
                "bm25": bm25_metrics,
                "dense": dense_metrics,
                "frozen": frozen_metrics,
            },
            "curve": curve,
            "operators": operators,
            "params": params,
        }
        out = settings.results_dir / "baselines.json"
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if curve:
            (settings.results_dir / "curve.json").write_text(json.dumps(curve, indent=2), encoding="utf-8")
            plot_curve(curve, payload["baselines"], settings.results_dir / "curve.png")
            print(f"plot -> {settings.results_dir / 'curve.png'}")
        print(f"wrote {out}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
