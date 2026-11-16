import numpy as np
from repocortex.retrieve.dense import build_dense_index


class Embedder:
    model_name = "fixture"

    def __init__(self):
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        return np.full((len(texts), 3), self.calls, dtype=np.float32)


def test_changed_text_with_same_uids_invalidates_dense_cache(tmp_path):
    cache = tmp_path / "embeddings.npz"
    nodes = {"func:a": {"label": "Function", "name": "a", "doc": "old text"}}
    embedder = Embedder()
    build_dense_index(nodes, embedder, cache)
    build_dense_index(nodes, embedder, cache)
    assert embedder.calls == 1
    nodes["func:a"]["doc"] = "new implementation context"
    result = build_dense_index(nodes, embedder, cache)
    assert embedder.calls == 2
    assert (result.matrix == 2).all()


def test_legacy_cache_without_text_hash_is_rebuilt(tmp_path):
    cache = tmp_path / "embeddings.npz"
    np.savez(cache, uids=["func:a"], matrix=np.zeros((1, 3)), model="fixture")
    embedder = Embedder()
    build_dense_index({"func:a": {"label": "Function", "name": "a"}}, embedder, cache)
    assert embedder.calls == 1
