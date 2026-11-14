"""Credit edges on paths that reached gold, and debit the rest of the neighborhood."""

from __future__ import annotations

from repocortex.learn.base import Episode, Operator, OperatorResult
from repocortex.retrieve.frozen import gold_paths


class EdgeReweighter(Operator):
    name = "edge_reweight"

    def __init__(self, lr: float = 0.2):
        self.lr = lr

    def on_outcome(self, table, episode: Episode) -> OperatorResult:
        good = gold_paths(episode.traversed, episode.seeds, episode.gold)
        applied = table.apply_rewards(episode.traversed, good, self.lr)
        return OperatorResult(
            name=self.name,
            applied=applied,
            detail=f"credited {len(good)} edges, lr {self.lr}",
        )


class PathCompressor(Operator):
    """Phase 2. Recurring 2-hop successes become a SHORTCUT edge."""

    name = "path_compression"

    def on_outcome(self, table, episode: Episode) -> OperatorResult:
        return OperatorResult(name=self.name, applied=0, detail="stub")


class GapIngestor(Operator):
    """Phase 2. If no path reaches gold, ingest the missing neighborhood."""

    name = "gap_ingestion"

    def on_outcome(self, table, episode: Episode) -> OperatorResult:
        reached = bool(gold_paths(episode.traversed, episode.seeds, episode.gold))
        detail = "path exists" if reached else "gap detected, ingestion not implemented"
        return OperatorResult(name=self.name, applied=0, detail=detail)


class EntityMerger(Operator):
    """Phase 2. SAME_AS for overlapping concepts, REFINES when one is split."""

    name = "entity_merge_split"

    def on_outcome(self, table, episode: Episode) -> OperatorResult:
        return OperatorResult(name=self.name, applied=0, detail="stub")
