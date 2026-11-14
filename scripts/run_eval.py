"""Score the held-out split and, with --replay, draw the learning curve."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repocortex.config import Settings
from repocortex.eval.harness import eval_bm25, eval_dense
from repocortex.eval.metrics import bootstrap_gap
from repocortex.eval.plot import plot_curve
from repocortex.graph.export import dump_graph
from repocortex.graph.ingest import clear_learned, load_graph
from repocortex.hydradb import connect
from repocortex.learn.replay import replay, rolling_mean
from repocortex.mine.dataset import load_dataset
from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.dense import Embedder, build_dense_index
from repocortex.retrieve.frozen import EdgeTable
from repocortex.retrieve.hybrid import HybridRanker, QueryCache

ABLATIONS = (
    ("learning off", "disabled", False),
    ("reweight", "reweight", False),
    ("+shortcuts", "shortcuts", False),
    ("+gap", "gap", False),
    ("full", "full", True),
)


def _public_metrics(metrics: dict) -> dict:
    return {key: value for key, value in metrics.items() if key != "per_issue"}


def _copy_nodes(nodes: dict) -> dict:
    return {uid: dict(node) for uid, node in nodes.items()}


def _prequential_summary(rows: list[dict], window: int) -> dict:
    if not rows:
        return {"n": 0, "window": window}
    acc = [float(row["function_acc@10"]) for row in rows]
    mrr = [float(row["mrr"]) for row in rows]
    rolled_acc = rolling_mean(acc, window)
    rolled_mrr = rolling_mean(mrr, window)
    head = min(window, len(rows))
    return {
        "n": len(rows),
        "window": window,
        "first_window_acc10": round(sum(acc[:head]) / head, 6),
        "last_window_acc10": round(rolled_acc[-1], 6),
        "first_window_mrr": round(sum(mrr[:head]) / head, 6),
        "last_window_mrr": round(rolled_mrr[-1], 6),
        "cumulative_acc10": round(sum(acc) / len(acc), 6),
        "cumulative_mrr": round(sum(mrr) / len(mrr), 6),
    }


def _prequential_points(rows: list[dict], window: int) -> list[dict]:
    if not rows:
        return []
    acc = [float(row["function_acc@10"]) for row in rows]
    mrr = [float(row["mrr"]) for row in rows]
    rolled_acc = rolling_mean(acc, window)
    rolled_mrr = rolling_mean(mrr, window)
    cumulative_acc = rolling_mean(acc, len(acc))
    cumulative_mrr = rolling_mean(mrr, len(mrr))
    points = []
    for index, row in enumerate(rows):
        points.append(
            {
                "index": row["index"],
                "ticket": row["ticket"],
                "time": row.get("time") or 0,
                "function_acc@10": row["function_acc@10"],
                "mrr": row["mrr"],
                "rolling_acc10": round(rolled_acc[index], 6),
                "rolling_mrr": round(rolled_mrr[index], 6),
                "cumulative_acc10": round(cumulative_acc[index], 6),
                "cumulative_mrr": round(cumulative_mrr[index], 6),
            }
        )
    return points


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    settings = Settings.load(root)
    parser = argparse.ArgumentParser(description="run baselines and the learning curve")
    parser.add_argument("--dataset", type=Path, default=settings.data_dir / "dataset.json")
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--points", type=int, default=15)
    parser.add_argument("--every", type=int, default=40, help="entity merge cadence, in train issues")
    parser.add_argument("--window", type=int, default=100, help="prequential rolling window")
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    holdout = [issue for issue in dataset["issues"] if issue["split"] == "test"]
    train = [issue for issue in dataset["issues"] if issue["split"] == "train"]
    print(f"train={len(train)} holdout={len(holdout)}", flush=True)
    client = connect(settings)
    try:
        nodes, edges, truncated = load_graph(client)
        print(f"graph nodes={len(nodes)} edges={len(edges)} truncated={truncated}", flush=True)
        if not any(node.get("label") == "Function" for node in nodes.values()):
            raise SystemExit("no functions in the graph; run scripts/build_graph.py")
        bm25 = BM25Index.from_nodes(nodes)
        bm25_metrics = eval_bm25(bm25, nodes, holdout)
        print("bm25", json.dumps(_public_metrics(bm25_metrics)), flush=True)
        print("loading sentence-transformers model", flush=True)
        embedder = Embedder()
        dense = build_dense_index(nodes, embedder, settings.data_dir / "embeddings.npz")
        dense_metrics = eval_dense(dense, embedder, nodes, holdout)
        print("dense", json.dumps(_public_metrics(dense_metrics)), flush=True)
        settings.results_dir.mkdir(parents=True, exist_ok=True)
        series = {}
        ablations = {}
        full = None
        frozen_metrics = {}
        if args.replay:
            print("replaying train issues", flush=True)
            clear_learned(client)
            shared_vec: dict = {}
            cache = QueryCache()
            for label, mode, record in ABLATIONS:
                print(f"ablation {label}", flush=True)
                ranker = HybridRanker(
                    _copy_nodes(nodes),
                    EdgeTable(edges),
                    bm25,
                    dense,
                    embedder,
                    client if mode == "full" else None,
                )
                ranker._vec = shared_vec
                ranker.score_cache = cache
                played = replay(
                    ranker,
                    train,
                    holdout,
                    every=args.every,
                    mode=mode,
                    points=args.points,
                    record_prequential=record,
                    snapshots=(mode == "full"),
                )
                series[label] = played["curve"]
                ablations[label] = {
                    "mode": mode,
                    "operators": played["operators"],
                    "final": played["curve"][-1],
                    "curve": played["curve"],
                }
                if mode == "disabled":
                    frozen_metrics = dict(played["curve"][0])
                    frozen_metrics.pop("step", None)
                if mode == "full":
                    full = (ranker, played)
            assert full is not None
            ranker, played = full
            window = args.window
            online = _prequential_points(played["prequential"], window)
            online_summary = _prequential_summary(played["prequential"], window)
            gap = bootstrap_gap(played["per_issue"], dense_metrics["per_issue"])
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
                "hits_with_graph": sum(
                    1
                    for issue in played["provenance"]
                    for hit in issue["hits"]
                    if any(rel in hit["path"] for rel in ("CALLS", "CO_CHANGED", "TESTED_BY", "DEFINES"))
                ),
                "issues": played["provenance"],
            }
            (settings.results_dir / "provenance.json").write_text(
                json.dumps(provenance, indent=2), encoding="utf-8"
            )
            (settings.results_dir / "snapshots.json").write_text(
                json.dumps(played["snapshots"], indent=2), encoding="utf-8"
            )
            graph_counts = dump_graph(ranker.nodes, ranker.edges, settings.results_dir / "graph.json")
            print(f"graph export {graph_counts}", flush=True)
            ranker.save(settings.data_dir / "learned_state.npz")
            curve_payload = {
                "series": series,
                "prequential": {"summary": online_summary, "points": online},
            }
            (settings.results_dir / "curve.json").write_text(
                json.dumps(curve_payload, indent=2), encoding="utf-8"
            )
            plot_curve(series, {"bm25": bm25_metrics, "dense": dense_metrics}, settings.results_dir / "curve.png", online, window)
            print(f"plot -> {settings.results_dir / 'curve.png'}", flush=True)
            try:
                print(
                    f"shortcuts={client.count_rel('SHORTCUT')} fixed_in={client.count_rel('FIXED_IN')}",
                    flush=True,
                )
            except Exception as exc:
                print(f"could not count learned edges: {exc}", flush=True)
            payload = _payload(
                dataset,
                settings,
                truncated,
                train,
                holdout,
                bm25_metrics,
                dense_metrics,
                frozen_metrics,
                played,
                ablations,
                gap,
                online_summary,
                graph_counts,
            )
        else:
            payload = _payload(
                dataset,
                settings,
                truncated,
                train,
                holdout,
                bm25_metrics,
                dense_metrics,
                {},
                None,
                {},
                {},
                {},
                {},
            )
        out = settings.results_dir / "baselines.json"
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {out}", flush=True)
    finally:
        client.close()


def _payload(dataset, settings, truncated, train, holdout, bm25_metrics, dense_metrics, frozen_metrics, played, ablations, gap, online_summary, graph_counts):
    def clean(metrics):
        if not metrics:
            return {}
        return _public_metrics(metrics)

    return {
        "snapshot": dataset["snapshot"],
        "scope": dataset["scope"],
        "backend": settings.backend,
        "hops": settings.hops,
        "train": len(train),
        "holdout": len(holdout),
        "truncated": truncated,
        "bootstrap": {"samples": 1000, "seed": 7, "level": 0.95},
        "baselines": {
            "bm25": clean(bm25_metrics),
            "dense": clean(dense_metrics),
            "frozen": clean(frozen_metrics),
        },
        "gap_learned_minus_dense": gap,
        "curve": played["curve"] if played else [],
        "ablations": {
            name: {"mode": body["mode"], "operators": body["operators"], "final": body["final"]}
            for name, body in ablations.items()
        },
        "operators": played["operators"] if played else {},
        "params": played["params"] if played else {},
        "prequential": online_summary,
        "graph": graph_counts,
        "note": (
            "frozen is the unlearned hybrid: dense plus a 0.10 BM25 blend plus one hop "
            "from those seeds over the code graph. It is not the older PageRank walk. "
            "Learning modes store each fix before the next prediction. "
            "reweight is that memory plus edge reweighting. "
            "+shortcuts, +gap, and full add those operators on top."
        ),
    }


if __name__ == "__main__":
    main()
