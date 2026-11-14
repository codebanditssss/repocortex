"""Replay train issues in time order and score the held-out set at checkpoints."""

from __future__ import annotations

from repocortex.eval.metrics import summarize
from repocortex.learn.base import Episode
from repocortex.learn.compress import PathCompressor
from repocortex.learn.credit import credit_and_debit
from repocortex.learn.gap import GapIngestor
from repocortex.learn.merge import EntityMerger
from repocortex.learn.reweight import EdgeReweighter


def replay(ranker, train: list[dict], holdout: list[dict], every: int = 40, lr: float = 0.25) -> dict:
    reweighter = EdgeReweighter(lr=lr)
    compressor = PathCompressor()
    gap = GapIngestor(nodes=getattr(ranker, "nodes", {}), ranker=ranker)
    merger = EntityMerger(ranker=ranker, every=every)
    operators = [gap, compressor, merger, reweighter]
    operator_totals = {op.name: 0 for op in operators}
    if hasattr(ranker, "prepare"):
        ranker.prepare(list(train) + list(holdout))
    curve = []
    provenance = []

    def checkpoint(step: int, capture: bool) -> None:
        rows = []
        captured = []
        for issue in holdout:
            pred = ranker.predict(issue, k=10)
            rows.append(
                {
                    "ranked": [hit.uid for hit in pred.hits],
                    "files": [hit.file for hit in pred.hits],
                    "gold": issue["gold_functions"],
                    "gold_files": issue["gold_files"],
                }
            )
            if capture:
                gold = set(issue["gold_functions"])
                captured.append(
                    {
                        "ticket": int(issue["ticket"]),
                        "gold": list(issue["gold_functions"]),
                        "hits": [
                            {
                                "rank": rank,
                                "uid": hit.uid,
                                "file": hit.file,
                                "score": round(hit.score, 4),
                                "gold": hit.uid in gold,
                                "path": hit.path,
                            }
                            for rank, hit in enumerate(pred.hits[:5], start=1)
                        ],
                    }
                )
        metrics = summarize(rows)
        metrics["step"] = step
        curve.append(metrics)
        print(
            f"  checkpoint {step} acc10={metrics['function_acc@10']:.4f} mrr={metrics['mrr']:.4f}",
            flush=True,
        )
        if capture:
            provenance.extend(captured)

    checkpoint(0, False)
    for index, issue in enumerate(train, start=1):
        if index % 20 == 0 or index == len(train):
            print(f"  replay {index}/{len(train)}", flush=True)
        pred = ranker.predict(issue, k=10)
        credit, debit, promoted = credit_and_debit(pred, issue["gold_functions"])
        episode = Episode(
            ticket=int(issue["ticket"]),
            seeds=list(pred.seeds),
            gold=list(issue["gold_functions"]),
            predicted=[hit.uid for hit in pred.hits],
            traversed=list(pred.traversed),
            credit=credit,
            debit=debit,
            concepts=list(pred.concepts),
            promoted=promoted,
            frontier=list(pred.frontier),
            gap_concepts=list(getattr(pred, "gap_concepts", []) or []),
        )
        for op in operators:
            result = op.on_outcome(ranker.edges, episode)
            operator_totals[result.name] += result.applied
        if hasattr(ranker, "observe"):
            ranker.observe(issue)
        if index % every == 0 or index == len(train):
            if hasattr(ranker, "flush"):
                ranker.flush()
            else:
                ranker.edges.flush(getattr(ranker, "client", None))
            checkpoint(index, index == len(train))
    params = {}
    for name in ("bm25_mix", "memory_lam", "memory_thresh", "memory_k", "shortcut_lam"):
        if hasattr(ranker, name):
            params[name] = getattr(ranker, name)
    return {
        "curve": curve,
        "operators": operator_totals,
        "provenance": provenance,
        "params": params,
        "lr": lr,
        "every": every,
    }
