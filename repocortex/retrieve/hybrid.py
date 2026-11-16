"""Rank functions from dense retrieval, then add what the graph has learned.

Step 0 is the frozen graph. Seeds are the top dense hits and the top BM25 hits.
One hop over CALLS, CO_CHANGED, TESTED_BY, and DEFINES is mixed in at
`graph_mix`, with each seed divided by the square root of its degree so a hub
does not take the whole hop. The BM25 blend was chosen on the last 40 training
issues of the smaller phase 2 set, which sat before that holdout. `graph_mix`
is a small fixed prior and was not fit on the held-out issues.

Later steps add learned terms on top of that frozen score:

- FIXED_IN from past issues whose text is close to this report
- a file or module prior from how often those functions were fixed before
- SHORTCUT from a concept or symptom that has repeatedly landed on a function

Reweighting changes the hop because the neighbor mass is multiplied by the edge
weight. The hop is then divided by its peak, so only the relative weights move
the ranking. Memory hyperparameters are fit on a late slice of the training
period, not on the holdout.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from threading import RLock

import numpy as np

from repocortex.graph.weights import edge_weight
from repocortex.learn.gap import gap_tokens, module_of
from repocortex.retrieve.frozen import EdgeTable, Hit, Prediction
from repocortex.retrieve.textutil import issue_text, tokenize


class QueryCache:
    """BM25 vectors reused across ablation rankers. Ticket 0 is never stored."""

    def __init__(self) -> None:
        self.bm25: dict[int, np.ndarray] = {}


def _unit(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if norm > 0:
        vector = vector / norm
    return vector


class HybridRanker:
    def __init__(
        self,
        nodes: dict,
        edges: EdgeTable,
        bm25,
        dense,
        embedder,
        client=None,
        bm25_mix: float = 0.10,
        memory_lam: float = 0.08,
        memory_thresh: float = 0.55,
        memory_k: int = 5,
        shortcut_lam: float = 0.04,
        shortcut_min_support: int = 3,
        shortcut_min_precision: float = 0.4,
        graph_mix: float = 0.05,
        memory_agg: str = "sum",
        memory_frontier: int = 0,
        recency_half_life: float = 0.0,
        file_prior_lam: float = 0.0,
        module_prior_lam: float = 0.0,
        prior_seeds: int = 12,
        generalize_concepts: bool = False,
        credit_decay: float = 0.08,
    ):
        self.nodes = nodes
        self.edges = edges
        self.bm25 = bm25
        self.embedder = embedder
        self.client = client
        self.live_graph = False
        self.request_lock = RLock()
        self.bm25_mix = bm25_mix
        self.memory_lam = memory_lam
        self.memory_thresh = memory_thresh
        self.memory_k = memory_k
        self.shortcut_lam = shortcut_lam
        self.shortcut_min_support = shortcut_min_support
        self.shortcut_min_precision = shortcut_min_precision
        self.graph_mix = graph_mix
        self.memory_agg = memory_agg if memory_agg in {"sum", "max"} else "sum"
        self.memory_frontier = max(0, int(memory_frontier or 0))
        self.recency_half_life = float(recency_half_life or 0.0)
        self.file_prior_lam = float(file_prior_lam or 0.0)
        self.module_prior_lam = float(module_prior_lam or 0.0)
        self.prior_seeds = max(1, int(prior_seeds))
        self.generalize_concepts = bool(generalize_concepts)
        self.credit_decay = float(credit_decay)
        self.func_uids = list(dense.uids)
        self.uid_index = {uid: index for index, uid in enumerate(self.func_uids)}
        self.matrix = np.asarray(dense.matrix, dtype=np.float32)
        self.n = len(self.func_uids)
        self.uid_array = np.array(self.func_uids)
        self.concepts = {
            node["name"]: uid
            for uid, node in nodes.items()
            if node.get("label") == "Concept" and node.get("name")
        }
        self.symptoms = [
            (uid, (node.get("name") or "").lower())
            for uid, node in nodes.items()
            if node.get("label") == "Symptom" and node.get("name")
        ]
        self.symptoms.sort(key=lambda item: -len(item[1]))
        self._vec: dict[int, np.ndarray] = {}
        self.score_cache = None
        self._local_bm25: dict[int, np.ndarray] = {}
        self.memory: list[dict] = []
        self.fix_count: dict[str, int] = {}
        self._seen = 0
        self._mem_mat: np.ndarray | None = None
        self._mem_dirty = True
        self.pending_nodes: dict[str, dict] = {}

    def add_node(self, uid: str, label: str, name: str, **extra) -> None:
        if uid in self.nodes and uid not in self.pending_nodes:
            return
        row = {
            "uid": uid,
            "label": label,
            "name": name,
            "file": extra.get("file", "") or "",
            "qualname": extra.get("qualname", "") or "",
            "signature": extra.get("signature", "") or "",
            "doc": extra.get("doc", "") or "",
            "start": int(extra.get("start") or 0),
            "end": int(extra.get("end") or 0),
            "kind": extra.get("kind") or label.lower(),
        }
        self.nodes[uid] = {
            "label": label,
            "name": name,
            "file": row["file"],
            "qualname": row["qualname"],
            "doc": row["doc"],
            "signature": row["signature"],
            "start": row["start"],
            "end": row["end"],
        }
        self.pending_nodes[uid] = row
        if label == "Concept" and name:
            self.concepts.setdefault(name, uid)

    def prepare(self, issues: list[dict]) -> None:
        missing = [issue for issue in issues if int(issue["ticket"]) not in self._vec]
        if not missing:
            return
        vectors = self.embedder.encode([issue_text(issue) for issue in missing])
        for issue, vector in zip(missing, vectors):
            self._vec[int(issue["ticket"])] = _unit(vector)

    def observe(self, issue: dict) -> str:
        """Remember this fix after the prediction, so the label cannot leak in."""
        ticket = int(issue["ticket"])
        text = issue_text(issue)
        vector = self._vec.get(ticket)
        if vector is None:
            vector = _unit(self.embedder.encode_one(text))
            self._vec[ticket] = vector
        uid = f"issue:{ticket}"
        self.add_node(uid, "Issue", f"#{ticket}", kind="issue")
        golds = [gold for gold in issue["gold_functions"] if gold in self.uid_index]
        self._seen += 1
        self.memory.append(
            {"uid": uid, "ticket": ticket, "golds": golds, "vec": vector, "index": self._seen}
        )
        self._mem_dirty = True
        for gold in golds:
            self.fix_count[gold] = self.fix_count.get(gold, 0) + 1
            self.edges.ensure(uid, "FIXED_IN", gold, w=1.0, hits=1, misses=0, count=1, learned=1)
        return uid

    def rebuild_history(self) -> None:
        """Rebuild fix counts from memory order. Used when a saved replay is reloaded."""
        self.fix_count = {}
        for index, item in enumerate(self.memory, start=1):
            item["index"] = index
            for gold in item.get("golds") or []:
                if gold not in self.uid_index:
                    continue
                self.fix_count[gold] = self.fix_count.get(gold, 0) + 1
        self._seen = len(self.memory)
        self._mem_dirty = True

    def gold_concepts(self, golds: list[str]) -> list[str]:
        """Concept nodes named by a fixed function, so a later similar symptom can reuse them.

        Called only after the prediction, so the current label does not score itself.
        """
        if not self.generalize_concepts:
            return []
        found: list[str] = []
        for gold in golds:
            node = self.nodes.get(gold) or {}
            text = f"{node.get('name') or ''} {node.get('qualname') or ''}"
            for token in tokenize(text):
                uid = self.concepts.get(token)
                if uid and uid not in found:
                    found.append(uid)
                if len(found) >= 6:
                    return found
        return found

    def flush(self) -> int:
        if self.client is None:
            return 0
        written = 0
        by_label: dict[str, list[dict]] = defaultdict(list)
        for row in self.pending_nodes.values():
            by_label[row["label"]].append(row)
        for label, rows in by_label.items():
            written += self.client.upsert_nodes(label, rows)
        self.pending_nodes.clear()
        written += self.edges.flush(self.client)
        return written

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        vectors = (
            np.vstack([item["vec"] for item in self.memory])
            if self.memory
            else np.zeros((0, self.matrix.shape[1]), dtype=np.float32)
        )
        learned = []
        for key, props in self.edges.edges.items():
            touched = (
                props.get("learned")
                or key[1] in {"SHORTCUT", "FIXED_IN", "SAME_AS", "REFINES"}
                or int(props.get("hits") or 0)
                or int(props.get("misses") or 0)
                or abs(edge_weight(props) - 1.0) > 1e-6
            )
            if not touched:
                continue
            learned.append(
                {
                    "src": key[0],
                    "rel": key[1],
                    "dst": key[2],
                    "w": edge_weight(props),
                    "hits": int(props.get("hits") or 0),
                    "misses": int(props.get("misses") or 0),
                    "tickets": props.get("tickets") or "",
                    "split": int(props.get("split") or 0),
                }
            )
        np.savez(
            path,
            vectors=vectors,
            tickets=np.array([item["ticket"] for item in self.memory]),
            golds=np.array([json.dumps(item["golds"]) for item in self.memory]),
        )
        path.with_suffix(".json").write_text(json.dumps(learned), encoding="utf-8")

    def predict(self, issue: dict, k: int = 10) -> Prediction:
        text = issue_text(issue)
        ticket = int(issue.get("ticket") or 0)
        vector = self._vec.get(ticket) if ticket else None
        if vector is None:
            vector = _unit(self.embedder.encode_one(text))
            if ticket:
                self._vec[ticket] = vector
        dense_scores = self.matrix @ vector
        bm25_norm = self._bm25_norm(text, ticket)
        base = dense_scores + np.float32(self.bm25_mix) * bm25_norm
        notes: dict[int, list[str]] = defaultdict(list)
        used: dict[int, list[tuple[str, str, str]]] = defaultdict(list)
        learned = np.zeros(self.n, dtype=np.float32)
        learned += self._memory_bonus(vector, notes, used, base)
        learned += self._history_prior(base, notes, "file")
        learned += self._history_prior(base, notes, "module")
        concepts = self._concept_seeds(text)
        modules = self._modules(base)
        learned += self._shortcut_bonus(concepts, modules, notes, used)
        learned += self._structural_bonus(dense_scores, bm25_norm, notes, used)
        scores = base + learned
        order = np.lexsort((self.uid_array, -scores))
        base_order = np.lexsort((self.uid_array, -base))
        hits = []
        support: dict[str, list[tuple[str, str, str]]] = {}
        for index in order[:k]:
            uid = self.func_uids[int(index)]
            path = " | ".join(notes.get(int(index), [])[:3]) or "dense + bm25"
            hits.append(
                Hit(
                    uid=uid,
                    file=(self.nodes.get(uid) or {}).get("file", ""),
                    score=float(scores[index]),
                    path=path,
                )
            )
        for index, keys in used.items():
            if keys:
                support[self.func_uids[index]] = list(keys)
        traversed = list(dict.fromkeys(key for keys in support.values() for key in keys))
        return Prediction(
            hits=hits,
            seeds=self._seeds(base_order, concepts),
            traversed=traversed,
            support_edges=support,
            base_topk=[self.func_uids[int(i)] for i in base_order[:k]],
            frontier=[self.func_uids[int(i)] for i in order[:30]],
            concepts=concepts,
            gap_concepts=gap_tokens(text, self.concepts),
        )

    def _bm25_norm(self, text: str, ticket: int = 0) -> np.ndarray:
        cache = self.score_cache.bm25 if self.score_cache is not None else self._local_bm25
        if ticket and ticket in cache:
            return cache[ticket]
        scores = np.zeros(self.n, dtype=np.float32)
        for uid, score in self.bm25.score_query(text).items():
            index = self.uid_index.get(uid)
            if index is not None:
                scores[index] = score
        peak = float(scores.max())
        if peak > 0:
            scores /= peak
        if ticket:
            cache[ticket] = scores
        return scores

    def _concept_seeds(self, text: str) -> list[str]:
        concepts = []
        for token in tokenize(text):
            uid = self.concepts.get(token)
            if uid and uid not in concepts:
                concepts.append(uid)
            if len(concepts) >= 8:
                break
        lowered = text.lower()
        symptoms = []
        for uid, name in self.symptoms:
            if len(name) < 5 or " " in name or len(name) > 80:
                continue
            if name in lowered:
                symptoms.append(uid)
                if len(symptoms) >= 4:
                    break
        return concepts + symptoms

    def _modules(self, base: np.ndarray) -> set[str]:
        order = np.argpartition(-base, min(4, self.n - 1))[:5] if self.n > 5 else np.argsort(-base)
        modules = set()
        for index in order:
            path = (self.nodes.get(self.func_uids[int(index)]) or {}).get("file", "")
            module = module_of(path)
            if module:
                modules.add(module)
        return modules

    def _memory_matrix(self) -> np.ndarray | None:
        if not self.memory:
            return None
        if self._mem_dirty or self._mem_mat is None:
            self._mem_mat = np.vstack([item["vec"] for item in self.memory])
            self._mem_dirty = False
        return self._mem_mat

    def _memory_bonus(self, vector, notes, used, base: np.ndarray | None = None) -> np.ndarray:
        bonus = np.zeros(self.n, dtype=np.float32)
        matrix = self._memory_matrix()
        if matrix is None or self.memory_lam <= 0:
            return bonus
        sims = matrix @ vector
        count = sims.shape[0]
        take = min(self.memory_k, count)
        if take == count:
            chosen = np.argsort(-sims)[:take]
        else:
            part = np.argpartition(-sims, take - 1)[:take]
            chosen = part[np.argsort(-sims[part])]
        raw = np.zeros(self.n, dtype=np.float32)
        span = max(1e-6, 1.0 - self.memory_thresh)
        newest = max((int(item.get("index") or 0) for item in self.memory), default=0)
        for index in chosen:
            sim = float(sims[int(index)])
            if sim < self.memory_thresh:
                continue
            scale = (sim - self.memory_thresh) / span
            item = self.memory[int(index)]
            if self.recency_half_life > 0 and newest:
                age = max(0, newest - int(item.get("index") or newest))
                scale *= 0.5 ** (age / self.recency_half_life)
            for gold in item["golds"]:
                column = self.uid_index.get(gold)
                if column is None:
                    continue
                key = (item["uid"], "FIXED_IN", gold)
                weight = 1.0
                props = self.edges.edges.get(key)
                if props is not None:
                    weight = min(1.15, max(0.85, edge_weight(props)))
                contrib = scale * weight
                if self.memory_agg == "max":
                    if contrib <= float(raw[column]):
                        continue
                    raw[column] = contrib
                    used[column] = [key]
                    notes[column] = [
                        f"issue #{item['ticket']} sim {sim:.2f} -FIXED_IN-> {self._label(gold)} (w {weight:.2f})"
                    ]
                else:
                    raw[column] += contrib
                    used[column].append(key)
                    notes[column].append(
                        f"issue #{item['ticket']} sim {sim:.2f} -FIXED_IN-> {self._label(gold)} (w {weight:.2f})"
                    )
        if self.memory_frontier > 0 and base is not None and self.n > self.memory_frontier:
            # A past fix may rerank a function the lexical score already surfaced.
            # It may not pull in a function the report did not otherwise suggest.
            keep = np.argpartition(-base, self.memory_frontier - 1)[: self.memory_frontier]
            allowed = np.zeros(self.n, dtype=bool)
            allowed[keep] = True
            for column in np.flatnonzero(~allowed & (raw > 0)):
                notes.pop(int(column), None)
                used.pop(int(column), None)
            raw[~allowed] = 0.0
        peak = float(raw.max())
        if peak > 0:
            bonus += np.float32(self.memory_lam) * (raw / peak)
        return bonus

    def _history_prior(self, base: np.ndarray, notes, kind: str) -> np.ndarray:
        """Boost functions already fixed in the files or modules the lexical ranker is looking at.

        Counts come only from fixes stored before this prediction. Step 0 has none.
        """
        bonus = np.zeros(self.n, dtype=np.float32)
        lam = self.file_prior_lam if kind == "file" else self.module_prior_lam
        if lam <= 0 or not self.fix_count or self.n == 0:
            return bonus
        take = min(self.prior_seeds, self.n)
        order = np.argpartition(-base, take - 1)[:take] if self.n > take else np.argsort(-base)
        seeds: set[str] = set()
        for index in order:
            path = (self.nodes.get(self.func_uids[int(index)]) or {}).get("file", "") or ""
            key = path if kind == "file" else module_of(path)
            if key:
                seeds.add(key)
        if not seeds:
            return bonus
        raw = np.zeros(self.n, dtype=np.float32)
        for uid, count in self.fix_count.items():
            column = self.uid_index.get(uid)
            if column is None or count <= 0:
                continue
            path = (self.nodes.get(uid) or {}).get("file", "") or ""
            key = path if kind == "file" else module_of(path)
            if key not in seeds:
                continue
            raw[column] = np.log1p(count)
        peak = float(raw.max())
        if peak <= 0:
            return bonus
        scaled = np.float32(lam) * (raw / np.float32(peak))
        label = "file prior" if kind == "file" else "module prior"
        for column in np.flatnonzero(raw >= 0.5 * peak):
            uid = self.func_uids[int(column)]
            notes[int(column)].append(f"{label} x{self.fix_count.get(uid, 0)} {self._label(uid)}")
        return scaled

    def _shortcut_bonus(self, concepts, modules, notes, used) -> np.ndarray:
        bonus = np.zeros(self.n, dtype=np.float32)
        if self.shortcut_lam <= 0 or not concepts:
            return bonus
        raw = np.zeros(self.n, dtype=np.float32)
        for concept in concepts:
            for column, precision, key, note in self._shortcut_targets(concept, modules)[:8]:
                raw[column] += precision
                used[column].append(key)
                notes[column].append(note)
        peak = float(raw.max())
        if peak > 0:
            bonus += np.float32(self.shortcut_lam) * (raw / peak)
        return bonus

    def _shortcut_targets(self, concept: str, modules: set[str]):
        refined = []
        if modules:
            for key in self.edges.incident(concept, "REFINES"):
                if key[0] != concept:
                    continue
                child = key[2]
                module = child.split("@")[-1] if "@" in child else ""
                if module in modules:
                    refined.append(child)
        sources = refined or [concept]
        found = []
        seen = set()
        for source in sources:
            for key in self.edges.incident(source, "SHORTCUT"):
                if key[0] != source:
                    continue
                props = self.edges.edges[key]
                if source == concept and props.get("split") and refined:
                    continue
                column = self.uid_index.get(key[2])
                if column is None or column in seen:
                    continue
                hits = int(props.get("hits") or 0)
                misses = int(props.get("misses") or 0)
                if hits < self.shortcut_min_support:
                    continue
                precision = hits / (hits + misses) if hits + misses else 0.0
                if precision < self.shortcut_min_precision:
                    continue
                seen.add(column)
                found.append(
                    (
                        column,
                        precision,
                        key,
                        f"{source} -SHORTCUT-> {self._label(key[2])} (hits {hits}, misses {misses})",
                    )
                )
        if not refined:
            for key in self.edges.incident(concept, "SAME_AS"):
                other = key[2] if key[0] == concept else key[0]
                for child in self.edges.incident(other, "SHORTCUT"):
                    if child[0] != other:
                        continue
                    props = self.edges.edges[child]
                    column = self.uid_index.get(child[2])
                    if column is None or column in seen:
                        continue
                    hits = int(props.get("hits") or 0)
                    misses = int(props.get("misses") or 0)
                    if hits < self.shortcut_min_support:
                        continue
                    precision = hits / (hits + misses) if hits + misses else 0.0
                    if precision < self.shortcut_min_precision:
                        continue
                    seen.add(column)
                    found.append(
                        (
                            column,
                            0.5 * precision,
                            child,
                            f"{concept} -SAME_AS-> {other} -SHORTCUT-> {self._label(child[2])}",
                        )
                    )
        found.sort(key=lambda item: (-item[1], self.func_uids[item[0]]))
        return found

    def _structural_bonus(self, dense_scores, bm25_norm, notes, used) -> np.ndarray:
        """One hop from the hybrid seeds. Weights of 1 still count, so step 0 uses the graph."""
        bonus = np.zeros(self.n, dtype=np.float32)
        if self.graph_mix <= 0 or self.n == 0:
            return bonus
        seeds: list[int] = []
        for scores in (dense_scores, bm25_norm):
            take = min(8, self.n)
            order = np.argpartition(-scores, take - 1)[:take] if self.n > take else np.argsort(-scores)
            for index in order:
                index = int(index)
                if float(scores[index]) <= 0 or index in seeds:
                    continue
                seeds.append(index)
        if not seeds:
            return bonus
        raw = np.zeros(self.n, dtype=np.float32)
        best: dict[int, tuple] = {}
        rels = {"CALLS", "CO_CHANGED", "TESTED_BY", "DEFINES"}
        live_edges = None
        if self.live_graph:
            live_edges = self.client.structural_edges([self.func_uids[i] for i in seeds])
        for index in seeds:
            seed = self.func_uids[index]
            seed_mass = max(float(dense_scores[index]), float(bm25_norm[index]))
            neighbors = []
            candidates = (
                [(key, weight) for key, weight in live_edges if seed in (key[0], key[2])]
                if live_edges is not None else
                [(key, edge_weight(self.edges.edges[key])) for key in self.edges.incident(seed)]
            )
            for key, weight in candidates:
                if key[1] not in rels:
                    continue
                other = key[2] if key[0] == seed else key[0]
                column = self.uid_index.get(other)
                if column is None:
                    continue
                neighbors.append((column, weight, key, other))
            if not neighbors:
                continue
            scale = seed_mass / (len(neighbors) ** 0.5)
            for column, weight, key, other in neighbors:
                gain = scale * max(weight, 0.0)
                if gain <= 0:
                    continue
                raw[column] += gain
                prev = best.get(column)
                if prev is None or gain > prev[0]:
                    arrow = f"-{key[1]}->" if key[0] == seed else f"<-{key[1]}-"
                    best[column] = (
                        gain,
                        key,
                        f"{self._label(seed)} {arrow} {self._label(other)} (w {weight:.2f})",
                    )
        peak = float(raw.max())
        if peak <= 0:
            return bonus
        scaled = np.float32(self.graph_mix) * (raw / np.float32(peak))
        # Keep each recipient's strongest representative edge and truthful path.
        # Display limits must not suppress credit or evidence for returned hits.
        for column, (_gain, key, note) in best.items():
            used[column].append(key)
            notes[column].append(note)
        return scaled

    def _seeds(self, base_order, concepts: list[str]) -> list[str]:
        lexical = [self.func_uids[int(i)] for i in base_order[:8]]
        return list(dict.fromkeys([*lexical, *concepts]))

    def _label(self, uid: str) -> str:
        node = self.nodes.get(uid) or {}
        return node.get("qualname") or node.get("name") or uid
