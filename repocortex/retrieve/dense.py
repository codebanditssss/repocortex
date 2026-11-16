"""Dense retrieval with a local sentence-transformers model."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from repocortex.retrieve.textutil import node_text

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class DenseIndex:
    def __init__(self, uids: list[str], matrix: np.ndarray):
        self.uids = uids
        # Rows are L2-normalized.
        self.matrix = matrix

    def score_query(self, vector: np.ndarray) -> dict[str, float]:
        sims = self.matrix @ vector
        return {uid: float(sims[i]) for i, uid in enumerate(self.uids)}

    def top(self, vector: np.ndarray, k: int) -> list[tuple[str, float]]:
        sims = self.matrix @ vector
        if len(sims) <= k:
            order = np.argsort(-sims)
        else:
            pick = np.argpartition(-sims, k)[:k]
            order = pick[np.argsort(-sims[pick])]
        return [(self.uids[i], float(sims[i])) for i in order]


class Embedder:
    def __init__(self, model_name: str = MODEL_NAME):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = self.model.encode(
            texts,
            batch_size=64,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return np.asarray(vectors, dtype=np.float32)

    def encode_one(self, text: str) -> np.ndarray:
        return self.encode([text])[0]


def build_dense_index(nodes: dict[str, dict], embedder: Embedder, cache: Path | None = None) -> DenseIndex:
    uids = sorted(uid for uid, node in nodes.items() if node.get("label") == "Function")
    texts = [node_text(nodes[uid]) for uid in uids]
    text_hash = hashlib.sha256(json.dumps(list(zip(uids, texts)), ensure_ascii=False,
                                        separators=(",", ":")).encode()).hexdigest()
    if cache and cache.is_file():
        with np.load(cache, allow_pickle=False) as blob:
            if (blob["uids"].tolist() == uids and str(blob["model"]) == embedder.model_name
                    and "text_sha256" in blob and str(blob["text_sha256"]) == text_hash):
                return DenseIndex(uids, blob["matrix"])

    matrix = embedder.encode(texts)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez(cache, uids=np.array(uids), matrix=matrix, model=np.array(embedder.model_name), text_sha256=np.array(text_hash))
    return DenseIndex(uids, matrix)
