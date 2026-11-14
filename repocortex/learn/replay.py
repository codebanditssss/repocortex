"""Replay train issues in time order and score the held-out set at checkpoints."""

from __future__ import annotations

from repocortex.learn.base import Episode
from repocortex.learn.reweight import EdgeReweighter, EntityMerger, GapIngestor, PathCompressor
from repocortex.eval.metrics import summarize


def replay(ranker, train: list[dict], holdout: list[dict], every: int = 50, lr: float = 0.2) -> dict:
    reweighter = EdgeReweighter(lr=lr)
    # The other operators are wired so the run records that they did not fire.
    others = [PathCompressor(), GapIngestor(), EntityMerger()]
    curve = []
    operator_totals = {op.name: 0 for op in [reweighter, *others]}

    def checkpoint(step: int) -> None:
        rows = []
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
        metrics = summarize(rows)
        metrics["step"] = step
        curve.append(metrics)

    checkpoint(0)
    for index, issue in enumerate(train, start=1):
        if index % 20 == 0 or index == len(train):
            print(f"  replay {index}/{len(train)}", flush=True)
        pred = ranker.predict(issue, k=10)
        episode = Episode(
            ticket=int(issue["ticket"]),
            seeds=pred.seeds,
            gold=list(issue["gold_functions"]),
            predicted=[hit.uid for hit in pred.hits],
            traversed=list(pred.traversed),
        )
        result = reweighter.on_outcome(ranker.edges, episode)
        operator_totals[result.name] += result.applied
        for op in others:
            extra = op.on_outcome(ranker.edges, episode)
            operator_totals[extra.name] += extra.applied
        if index % every == 0 or index == len(train):
            ranker.edges.flush(ranker.client)
            checkpoint(index)
    return {"curve": curve, "operators": operator_totals, "lr": lr, "every": every}
