"""When a gold function is outside the frontier, link the neighborhood we have.

A same-file function already in the frontier gets a learned CO_CHANGED edge.
A test whose name contains the function name gets TESTED_BY. Two specific
tokens from the report are added as concept seeds so a later repeat can
compress into a SHORTCUT. Nothing here is written for the held-out split.
"""

from __future__ import annotations

from repocortex.graph.weights import edge_weight
from repocortex.learn.base import Episode, Operator, OperatorResult
from repocortex.retrieve.textutil import tokenize

_STOP = {
    "self", "cls", "args", "kwargs", "true", "false", "none", "return",
    "test", "tests", "with", "from", "this", "that", "into", "over",
    "data", "value", "values", "result", "results", "object", "objects",
    "when", "should", "would", "could", "django", "error", "using",
    "have", "been", "does", "fixed", "query", "model", "field", "form",
}


def _module(path: str) -> str:
    parts = [part for part in (path or "").split("/") if part]
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return parts[0] if parts else ""


class GapIngestor(Operator):
    name = "gap_ingestion"

    def __init__(self, nodes: dict | None = None, ranker=None):
        self.ranker = ranker
        self.nodes = nodes if nodes is not None else getattr(ranker, "nodes", {}) or {}
        self.tests = [
            (uid, (node.get("name") or "").lower())
            for uid, node in self.nodes.items()
            if node.get("label") == "Test" and node.get("name")
        ]

    def on_outcome(self, table, episode: Episode) -> OperatorResult:
        if not episode.frontier:
            return OperatorResult(name=self.name, applied=0, detail="no frontier")
        frontier = set(episode.frontier)
        applied = 0
        notes = []
        for gold in episode.gold:
            if gold in frontier:
                continue
            node = self.nodes.get(gold) or {}
            file_name = node.get("file") or ""
            bridge = self._same_file(file_name, episode.frontier)
            if bridge:
                key = (bridge, "CO_CHANGED", gold)
                created = table.ensure(bridge, "CO_CHANGED", gold, learned=1)
                props = table.edges[key]
                props["learned"] = 1
                if created or edge_weight(props) < 1.15:
                    props["w"] = 1.15
                table.dirty.add(key)
                applied += 1
                notes.append("co_changed")
            short = (node.get("qualname") or node.get("name") or "").split(".")[-1].lower()
            if len(short) >= 8:
                for test_uid, test_name in self.tests:
                    if short in test_name:
                        key = (gold, "TESTED_BY", test_uid)
                        table.ensure(gold, "TESTED_BY", test_uid, learned=1, w=1.0)
                        table.edges[key]["learned"] = 1
                        table.dirty.add(key)
                        applied += 1
                        notes.append("tested_by")
                        break
        unreachable = [gold for gold in episode.gold if gold not in frontier]
        extra = self._extra_concepts(episode) if unreachable else []
        for concept in extra:
            self._register(concept)
            if concept not in episode.concepts:
                episode.concepts.append(concept)
                applied += 1
        detail = ",".join(notes) if notes else ("concepts" if extra else "no gap")
        return OperatorResult(name=self.name, applied=applied, detail=detail)

    def _register(self, concept: str) -> None:
        if self.ranker is None or not hasattr(self.ranker, "add_node"):
            return
        if concept in self.ranker.nodes:
            return
        name = concept.split(":", 1)[-1]
        self.ranker.add_node(concept, "Concept", name, kind="concept")
        self.nodes[concept] = self.ranker.nodes[concept]

    def _same_file(self, file_name: str, frontier: list[str]) -> str:
        if not file_name:
            return ""
        for uid in frontier[:15]:
            node = self.nodes.get(uid) or {}
            if node.get("label") == "Function" and node.get("file") == file_name:
                return uid
        return ""

    def _extra_concepts(self, episode: Episode) -> list[str]:
        # The report text is not on the episode. Concept seeds already chosen
        # by the ranker are the bridge; gap only adds tokens the ranker stashed
        # on the episode under a private attribute when it wants them counted.
        pending = list(getattr(episode, "gap_concepts", []) or [])
        return [uid for uid in pending if uid not in episode.concepts][:2]


def gap_tokens(text: str, known: dict[str, str]) -> list[str]:
    """Specific tokens from the report. New concept ids come first."""
    fresh: list[str] = []
    known_uids: list[str] = []
    seen = set()
    for token in tokenize(text):
        if len(token) < 6 or token in _STOP or token.isdigit() or token in seen:
            continue
        seen.add(token)
        if token in known:
            known_uids.append(known[token])
        else:
            fresh.append(token)
    fresh.sort(key=len, reverse=True)
    uids = [f"concept:{token}" for token in fresh[:2]]
    for uid in known_uids:
        if len(uids) >= 2:
            break
        if uid not in uids:
            uids.append(uid)
    return uids[:2]


def module_of(path: str) -> str:
    return _module(path)
