"""Operator interfaces. An episode is one train issue after its prediction."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Episode:
    ticket: int
    seeds: list[str]
    gold: list[str]
    predicted: list[str]
    traversed: list[tuple[str, str, str]] = field(default_factory=list)
    # None means "derive from traversed". An empty list means nothing to update.
    credit: list[tuple[str, str, str]] | None = None
    debit: list[tuple[str, str, str]] | None = None
    concepts: list[str] = field(default_factory=list)
    promoted: list[str] = field(default_factory=list)
    frontier: list[str] = field(default_factory=list)
    gap_concepts: list[str] = field(default_factory=list)


@dataclass
class OperatorResult:
    name: str
    applied: int
    detail: str


class Operator:
    name = "operator"

    def on_outcome(self, table, episode: Episode) -> OperatorResult:
        raise NotImplementedError
