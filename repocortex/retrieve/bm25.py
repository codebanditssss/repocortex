"""BM25 over function documents. Scoring uses an inverted index."""

from __future__ import annotations

import math
from collections import defaultdict

from repocortex.retrieve.textutil import node_text, tokenize


class BM25Index:
    def __init__(self, uids: list[str], docs: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.uids = uids
        self.k1 = k1
        self.b = b
        self.df: dict[str, int] = defaultdict(int)
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.dl: list[int] = []
        for index, doc in enumerate(docs):
            tf: dict[str, int] = defaultdict(int)
            for token in doc:
                tf[token] += 1
            self.dl.append(len(doc) or 1)
            for token, freq in tf.items():
                self.df[token] += 1
                self.postings[token].append((index, freq))
        self.avgdl = (sum(self.dl) / len(self.dl)) if self.dl else 1.0
        self.n = len(docs)
        self.idf = {
            token: math.log(1.0 + (self.n - df + 0.5) / (df + 0.5))
            for token, df in self.df.items()
        }

    @classmethod
    def from_nodes(cls, nodes: dict[str, dict]) -> "BM25Index":
        uids = [uid for uid, node in nodes.items() if node.get("label") == "Function"]
        uids.sort()
        docs = [tokenize(node_text(nodes[uid])) for uid in uids]
        return cls(uids, docs)

    def score_query(self, text: str) -> dict[str, float]:
        scores: dict[int, float] = defaultdict(float)
        seen = set()
        for token in tokenize(text):
            if token in seen or token not in self.postings:
                continue
            seen.add(token)
            idf = self.idf[token]
            for index, freq in self.postings[token]:
                denom = freq + self.k1 * (1.0 - self.b + self.b * self.dl[index] / self.avgdl)
                scores[index] += idf * (freq * (self.k1 + 1.0)) / denom
        return {self.uids[index]: score for index, score in scores.items()}

    def top(self, text: str, k: int) -> list[tuple[str, float]]:
        ranked = sorted(self.score_query(text).items(), key=lambda item: (-item[1], item[0]))
        return ranked[:k]
