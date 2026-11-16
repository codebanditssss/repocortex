"""Turn a repeated concept-to-fix association into a SHORTCUT edge.

The edge is written once support and precision both clear the bar. A later
miss on a shortcut that actually promoted a wrong top-k hit lowers precision
and can retire the edge. Ticket ids are kept so a path can name its evidence.
"""

from __future__ import annotations

from collections import defaultdict

from repocortex.learn.base import Episode, Operator, OperatorResult


class PathCompressor(Operator):
    name = "path_compression"

    def __init__(self, min_support: int = 3, min_precision: float = 0.4):
        self.min_support = min_support
        self.min_precision = min_precision
        self.hits: dict[tuple[str, str], int] = defaultdict(int)
        self.misses: dict[tuple[str, str], int] = defaultdict(int)
        self.tickets: dict[tuple[str, str], list[int]] = defaultdict(list)

    def hydrate(self, table) -> None:
        """Reload support from SHORTCUT edges so a later fix does not reset them."""
        for (src, rel, dst), props in table.edges.items():
            if rel != "SHORTCUT":
                continue
            pair = (src, dst)
            self.hits[pair] = int(props.get("hits") or 0)
            self.misses[pair] = int(props.get("misses") or 0)
            raw = str(props.get("tickets") or "")
            self.tickets[pair] = [int(part) for part in raw.split(",") if part.strip().isdigit()]

    def _load_pair(self, table, pair: tuple[str, str]) -> None:
        """Seed counters for edges created by another operator after hydration."""
        if pair in self.hits:
            return
        props = table.edges.get((pair[0], "SHORTCUT", pair[1]), {})
        self.hits[pair] = int(props.get("hits") or 0)
        self.misses[pair] = int(props.get("misses") or 0)
        raw = str(props.get("tickets") or "")
        self.tickets[pair] = [int(part) for part in raw.split(",") if part.strip().isdigit()]

    def on_outcome(self, table, episode: Episode) -> OperatorResult:
        applied = 0
        gold = [uid for uid in episode.gold if uid]
        concepts = list(dict.fromkeys(episode.concepts))
        for concept in concepts:
            for target in gold:
                pair = (concept, target)
                self._load_pair(table, pair)
                self.hits[pair] += 1
                self.tickets[pair].append(episode.ticket)
                if self._sync(table, concept, target):
                    applied += 1
        for src, rel, dst in episode.debit or []:
            if rel != "SHORTCUT":
                continue
            pair = (src, dst)
            if pair[1] in gold:
                continue
            self._load_pair(table, pair)
            self.misses[pair] += 1
            self._sync(table, src, dst)
            applied += 1
        return OperatorResult(
            name=self.name,
            applied=applied,
            detail=f"tracked {len(self.hits)} concept-function pairs",
        )

    def _sync(self, table, src: str, dst: str) -> bool:
        hits = self.hits[(src, dst)]
        misses = self.misses[(src, dst)]
        precision = hits / (hits + misses) if hits + misses else 0.0
        tickets = ",".join(str(ticket) for ticket in self.tickets[(src, dst)][-8:])
        key = (src, "SHORTCUT", dst)
        ready = hits >= self.min_support and precision >= self.min_precision
        if ready:
            table.ensure(
                src,
                "SHORTCUT",
                dst,
                replace=True,
                w=round(precision, 4),
                hits=hits,
                misses=misses,
                count=hits,
                learned=1,
                tickets=tickets,
            )
            return True
        if key in table.edges:
            props = table.edges[key]
            props["w"] = round(min(float(props.get("w") or 0.0), precision), 4)
            props["hits"] = hits
            props["misses"] = misses
            props["count"] = hits
            props["tickets"] = tickets
            table.dirty.add(key)
        return False
