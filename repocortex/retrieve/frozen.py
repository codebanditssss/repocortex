"""Frozen-graph retrieval: lexical seeds, bounded traversal, client-side PPR."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.ppr import personalized_pagerank
from repocortex.retrieve.textutil import issue_text, tokenize


@dataclass
class Hit:
    uid: str
    file: str
    score: float
    path: str = ""


@dataclass
class Prediction:
    hits: list[Hit]
    seeds: list[str]
    traversed: list[tuple[str, str, str]] = field(default_factory=list)
    # uid -> edges that added learned boost for that function
    support_edges: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)
    base_topk: list[str] = field(default_factory=list)
    frontier: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    gap_concepts: list[str] = field(default_factory=list)


class EdgeTable:
    """Edge weights mirrored from HydraDB. Learning updates this, then flushes."""

    def __init__(self, edges: dict[tuple[str, str, str], dict]):
        self.edges = {key: dict(value) for key, value in edges.items()}
        self.dirty: set[tuple[str, str, str]] = set()
        # Edges created in this process. Flush inserts them; later edits only SET.
        self.fresh: set[tuple[str, str, str]] = set()
        self.by_node: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for key in self.edges:
            self.by_node[key[0]].append(key)
            self.by_node[key[2]].append(key)

    def incident(self, uid: str, rel: str | None = None):
        for key in self.by_node.get(uid, ()):
            if rel is None or key[1] == rel:
                yield key

    def ensure(self, src: str, rel: str, dst: str, replace: bool = False, **props) -> bool:
        """Create an edge, or update one that already exists when replace is set."""
        if not src or not dst or src == dst:
            return False
        key = (src, rel, dst)
        created = key not in self.edges
        if created:
            self.edges[key] = {
                "w": 1.0,
                "hits": 0,
                "misses": 0,
                "count": 1,
                "learned": 1,
                "tickets": "",
            }
            self.by_node[src].append(key)
            self.by_node[dst].append(key)
            self.fresh.add(key)
        if created or replace:
            self.edges[key].update(props)
        else:
            for name, value in props.items():
                self.edges[key].setdefault(name, value)
        self.dirty.add(key)
        return created

    def nudge(self, key: tuple[str, str, str], reward: float, lr: float = 0.25, decay: float = 0.08) -> None:
        """Move one edge toward a high or low target, then shrink the gap to 1."""
        props = self.edges.get(key)
        if props is None:
            return
        if reward >= 0.5:
            props["hits"] = int(props.get("hits") or 0) + 1
        else:
            props["misses"] = int(props.get("misses") or 0) + 1
        target = 0.55 + 0.8 * float(reward)
        weight = float(props.get("w") or 1.0)
        weight = weight + lr * (target - weight)
        weight = 1.0 + (weight - 1.0) * (1.0 - decay)
        props["w"] = min(2.2, max(0.35, weight))
        self.dirty.add(key)

    def undirected(self, nodes: set[str]) -> dict[str, list[tuple[str, float]]]:
        adj: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for (src, _rel, dst), props in self.edges.items():
            if src in nodes and dst in nodes:
                weight = float(props.get("w") or 1.0)
                adj[src].append((dst, weight))
                adj[dst].append((src, weight))
        return adj

    def near_seeds(self, seeds: list[str], hops: int, cap: int = 800) -> list[tuple[str, str, str]]:
        """Directed edges within `hops` of a seed, used as the debit/credit set."""
        allowed = set(seeds)
        frontier = list(seeds)
        found: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for _ in range(max(1, hops)):
            nxt: list[str] = []
            for uid in frontier:
                for key in self._touching(uid):
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append(key)
                    src, _rel, dst = key
                    other = dst if src == uid else src
                    if other not in allowed:
                        allowed.add(other)
                        nxt.append(other)
                    if len(found) >= cap:
                        return found
            frontier = nxt
            if not frontier:
                break
        return found

    def _touching(self, uid: str):
        return self.by_node.get(uid, ())

    def apply_rewards(self, keys: list[tuple[str, str, str]], good: set[tuple[str, str, str]], lr: float) -> int:
        changed = 0
        for key in keys:
            props = self.edges.get(key)
            if props is None:
                continue
            reward = 1.0 if key in good else 0.0
            if reward >= 0.5:
                props["hits"] = int(props.get("hits") or 0) + 1
            else:
                props["misses"] = int(props.get("misses") or 0) + 1
            weight = float(props.get("w") or 1.0)
            weight = weight + lr * (reward - weight)
            props["w"] = min(3.0, max(0.05, weight))
            self.dirty.add(key)
            changed += 1
        return changed

    def flush(self, client) -> int:
        if client is None or not self.dirty:
            return 0
        fresh_rows: dict[str, list[dict]] = defaultdict(list)
        old_rows: dict[str, list[dict]] = defaultdict(list)
        done_fresh: list[tuple[str, str, str]] = []
        for key in list(self.dirty):
            props = self.edges[key]
            src, rel, dst = key
            row = {
                "src": src,
                "dst": dst,
                "w": float(props.get("w") or 1.0),
                "hits": int(props.get("hits") or 0),
                "misses": int(props.get("misses") or 0),
                "count": int(props.get("count") or 1),
            }
            if key in self.fresh:
                fresh_rows[rel].append(row)
                done_fresh.append(key)
            else:
                old_rows[rel].append(row)
        written = 0
        for rel, rows in fresh_rows.items():
            written += client.upsert_edges(rel, rows)
        for rel, rows in old_rows.items():
            written += client.update_edge_weights(rel, rows)
        for key in done_fresh:
            self.fresh.discard(key)
        self.dirty.clear()
        return written


def gold_paths(traversed: list[tuple[str, str, str]], seeds: list[str], gold: list[str]) -> set[tuple[str, str, str]]:
    """Edges that sit on a shortest path from any seed to a gold function."""
    adj: dict[str, list[tuple[str, tuple[str, str, str]]]] = defaultdict(list)
    for key in traversed:
        src, _rel, dst = key
        adj[src].append((dst, key))
        adj[dst].append((src, key))
    good: set[tuple[str, str, str]] = set()
    for target in gold:
        parent: dict[str, tuple[str, tuple[str, str, str]] | None] = {seed: None for seed in seeds}
        queue: deque[str] = deque(seeds)
        hit = False
        while queue:
            cur = queue.popleft()
            if cur == target:
                hit = True
                break
            for nxt, key in adj.get(cur, []):
                if nxt not in parent:
                    parent[nxt] = (cur, key)
                    queue.append(nxt)
        if not hit or target not in parent:
            continue
        cur = target
        while parent.get(cur):
            prev, key = parent[cur]
            good.add(key)
            cur = prev
    return good


class FrozenRanker:
    def __init__(
        self,
        nodes: dict[str, dict],
        edges: EdgeTable,
        bm25: BM25Index,
        client,
        hops: int = 2,
        # Restart at 0.5 keeps lexical seeds from being buried by hubs.
        # lexical_mix blends that PPR score with BM25 on the same candidates.
        teleport: float = 0.5,
        hub_norm: bool = False,
        lexical_mix: float = 0.35,
    ):
        self.nodes = nodes
        self.edges = edges
        self.bm25 = bm25
        self.client = client
        self.hops = hops
        self.teleport = teleport
        self.hub_norm = hub_norm
        self.lexical_mix = lexical_mix
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

    def predict(self, issue: dict, k: int = 10) -> Prediction:
        text = issue_text(issue)
        lexical = self.bm25.score_query(text)
        top = sorted(lexical, key=lambda uid: (-lexical[uid], uid))[:15]
        query_tokens = set(tokenize(text))
        concept_seeds = [self.concepts[token] for token in query_tokens if token in self.concepts][:10]
        lowered = text.lower()
        symptom_seeds = [uid for uid, name in self.symptoms if name and name in lowered][:8]
        seeds = list(dict.fromkeys([*top, *concept_seeds, *symptom_seeds]))
        expanded = self.client.expand(seeds, hops=self.hops, limit=250)
        paths = {}
        candidates = set(top)
        for hit in expanded.hits:
            node = self.nodes.get(hit.uid)
            if node and node.get("label") == "Function":
                candidates.add(hit.uid)
                paths.setdefault(hit.uid, hit.path)
        personal = {}
        peak = max((lexical[uid] for uid in top), default=1.0) or 1.0
        for uid in top:
            personal[uid] = lexical[uid] / peak
        for uid in concept_seeds + symptom_seeds:
            personal[uid] = max(personal.get(uid, 0.0), 1.0)
        sub = set(candidates) | set(concept_seeds) | set(symptom_seeds)
        adj = self.edges.undirected(sub)
        if self.hub_norm:
            degree = {uid: sum(weight for _, weight in nbrs) or 1.0 for uid, nbrs in adj.items()}
            adj = {
                uid: [(nbr, weight / ((degree.get(uid, 1.0) * degree.get(nbr, 1.0)) ** 0.5)) for nbr, weight in nbrs]
                for uid, nbrs in adj.items()
            }
        rank = personalized_pagerank(sorted(sub), adj, personal, teleport=self.teleport)
        hits = []
        peak_p = max((rank.get(uid, 0.0) for uid in candidates), default=1.0) or 1.0
        peak_b = max((lexical.get(uid, 0.0) for uid in candidates), default=1.0) or 1.0
        mix = self.lexical_mix
        for uid in candidates:
            node = self.nodes.get(uid) or {}
            if node.get("label") != "Function":
                continue
            blended = (1.0 - mix) * (rank.get(uid, 0.0) / peak_p) + mix * (lexical.get(uid, 0.0) / peak_b)
            hits.append(
                Hit(
                    uid=uid,
                    file=node.get("file") or "",
                    score=blended,
                    path=paths.get(uid, ""),
                )
            )
        hits.sort(key=lambda hit: (-hit.score, -lexical.get(hit.uid, 0.0), hit.uid))
        traversed = self.edges.near_seeds(seeds, self.hops, cap=250)
        return Prediction(hits=hits[:k], seeds=seeds, traversed=traversed)
