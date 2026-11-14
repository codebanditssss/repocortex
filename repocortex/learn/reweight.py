"""Credit edges on paths that reached gold. Debit edges that promoted a miss.

Weights move toward a high target on a credit and a low target on a debit,
then decay back toward 1 so a few updates cannot run away. Edges that were
only nearby are not touched. SHORTCUT weights are owned by path compression.
"""

from __future__ import annotations

from repocortex.learn.base import Episode, Operator, OperatorResult
from repocortex.retrieve.frozen import gold_paths


class EdgeReweighter(Operator):
    name = "edge_reweight"

    def __init__(self, lr: float = 0.25, decay: float = 0.08):
        self.lr = lr
        self.decay = decay

    def on_outcome(self, table, episode: Episode) -> OperatorResult:
        if episode.credit is None:
            credit = gold_paths(episode.traversed, episode.seeds, episode.gold)
        else:
            credit = set(episode.credit)
        if episode.debit is None:
            wrong = [uid for uid in episode.predicted if uid not in set(episode.gold)]
            debit = gold_paths(episode.traversed, episode.seeds, wrong) - credit
        else:
            debit = set(episode.debit) - set(credit)
        applied = 0
        for key in credit:
            if key[1] == "SHORTCUT" or key not in table.edges:
                continue
            table.nudge(key, 1.0, self.lr, self.decay)
            applied += 1
        for key in debit:
            if key[1] == "SHORTCUT" or key not in table.edges:
                continue
            table.nudge(key, 0.0, self.lr, self.decay)
            applied += 1
        return OperatorResult(
            name=self.name,
            applied=applied,
            detail=f"credited {len(credit)} debited {len(debit)}",
        )
