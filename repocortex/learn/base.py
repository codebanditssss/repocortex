"""Operator interfaces. Phase 2 fills in the three stubs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Episode:
    ticket: int
    seeds: list[str]
    gold: list[str]
    predicted: list[str]
    traversed: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class OperatorResult:
    name: str
    applied: int
    detail: str


class Operator:
    name = "operator"

    def on_outcome(self, table, episode: Episode) -> OperatorResult:
        raise NotImplementedError
