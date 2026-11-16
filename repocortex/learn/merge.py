"""SAME_AS when two concepts fix the same functions. REFINES when one is too broad.

Merge follows a shared target set. Split keeps a high-fan-out concept from
voting for every module: each module with repeated targets becomes its own
concept, and scoring uses that child when the dense seeds sit in the module.
"""

from __future__ import annotations

from collections import defaultdict

from repocortex.learn.base import Episode, Operator, OperatorResult
from repocortex.learn.gap import module_of


class EntityMerger(Operator):
    name = "entity_merge_split"

    def __init__(self, ranker=None, every: int = 40):
        self.ranker = ranker
        self.every = every
        self.seen = 0

    def on_outcome(self, table, episode: Episode) -> OperatorResult:
        self.seen += 1
        if self.seen % self.every != 0:
            return OperatorResult(name=self.name, applied=0, detail="waiting")
        groups: dict[str, set[str]] = defaultdict(set)
        precision: dict[str, list[float]] = defaultdict(list)
        for (src, rel, dst), props in table.edges.items():
            if rel != "SHORTCUT" or "@" in src:
                continue
            hits = int(props.get("hits") or 0)
            misses = int(props.get("misses") or 0)
            if hits < 2:
                continue
            groups[src].add(dst)
            precision[src].append(hits / (hits + misses) if hits + misses else 0.0)
        applied = 0
        sources = [src for src, targets in groups.items() if len(targets) >= 3]
        for index, left in enumerate(sources):
            for right in sources[index + 1 :]:
                shared = groups[left] & groups[right]
                if len(shared) < 3:
                    continue
                jac = len(shared) / len(groups[left] | groups[right])
                if jac < 0.55:
                    continue
                table.ensure(left, "SAME_AS", right, replace=True, w=round(jac, 4), hits=len(shared), learned=1)
                table.ensure(right, "SAME_AS", left, replace=True, w=round(jac, 4), hits=len(shared), learned=1)
                applied += 1
        nodes = getattr(self.ranker, "nodes", {}) if self.ranker is not None else {}
        for src, targets in groups.items():
            if len(targets) < 10:
                continue
            scores = precision[src]
            mean = sum(scores) / len(scores) if scores else 1.0
            if mean >= 0.35:
                continue
            by_module: dict[str, list[str]] = defaultdict(list)
            for dst in targets:
                module = module_of((nodes.get(dst) or {}).get("file", ""))
                if module:
                    by_module[module].append(dst)
            parent = nodes.get(src) or {}
            parent_name = parent.get("name") or src.split(":", 1)[-1]
            created_child = False
            for module, dsts in by_module.items():
                if len(dsts) < 2:
                    continue
                child = f"{src}@{module}"
                if self.ranker is not None and hasattr(self.ranker, "add_node"):
                    self.ranker.add_node(child, "Concept", f"{parent_name}@{module}", kind="refined")
                table.ensure(src, "REFINES", child, learned=1, w=1.0)
                for dst in dsts:
                    old = table.edges.get((src, "SHORTCUT", dst), {})
                    table.ensure(
                        child,
                        "SHORTCUT",
                        dst,
                        # Inherit once; subsequent outcomes belong to the child.
                        w=float(old.get("w") or 0.5),
                        hits=int(old.get("hits") or 0),
                        misses=int(old.get("misses") or 0),
                        count=int(old.get("count") or 0),
                        learned=1,
                        tickets=old.get("tickets") or "",
                    )
                created_child = True
            if created_child:
                for dst in targets:
                    props = table.edges.get((src, "SHORTCUT", dst))
                    if props is None:
                        continue
                    props["split"] = 1
                    table.dirty.add((src, "SHORTCUT", dst))
                applied += 1
        return OperatorResult(name=self.name, applied=applied, detail=f"concepts {len(groups)}")
