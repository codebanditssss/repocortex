"""Structural evidence must cover every scored recipient."""

from collections import defaultdict
from types import SimpleNamespace

import numpy as np
import pytest

from repocortex.learn.credit import credit_and_debit
from repocortex.retrieve.dense import DenseIndex
from repocortex.retrieve.frozen import EdgeTable
from repocortex.retrieve.hybrid import HybridRanker


def make_ranker(size, live):
    uids = [f"func:generic.py:f{i:03}" for i in range(size)]
    nodes = {
        uid: {"label": "Function", "qualname": f"generic.f{i:03}", "file": "generic.py"}
        for i, uid in enumerate(uids)
    }
    matrix = np.tile([0.0, 1.0], (size, 1)).astype(np.float32)
    matrix[0] = [1.0, 0.0]
    edges = EdgeTable({})
    ranker = HybridRanker(
        nodes, edges, SimpleNamespace(score_query=lambda text: {}),
        DenseIndex(uids, matrix),
        SimpleNamespace(encode_one=lambda text: np.array([1.0, 0.0], dtype=np.float32)),
        bm25_mix=0, memory_lam=0, shortcut_lam=0,
        client=SimpleNamespace(structural_edges=lambda seeds: [
            (key, float(props["w"])) for key, props in edges.edges.items()
        ]),
    )
    ranker.live_graph = live
    return ranker


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("high_base", [False, True])
def test_all_destinations_keep_support_and_paths_beyond_old_cap(live, high_base):
    ranker = make_ranker(44, live)
    uids = ranker.func_uids
    for i, uid in enumerate(uids[1:], 1):
        ranker.edges.ensure(uids[0], "CALLS", uid, w=1 + i / 100)
    if high_base:
        ranker.matrix[1] = [0.99, np.sqrt(1 - 0.99 ** 2)]

    # Original star-graph formula, including float32 accumulation/normalization.
    base = ranker.matrix[:, 0]
    raw = np.zeros(44, dtype=np.float32)
    for i in range(1, 44):
        raw[i] += (1 + i / 100) / (43 ** 0.5)
    if high_base:
        raw[0] += float(base[1]) * 1.01
    expected_bonus = np.float32(ranker.graph_mix) * (raw / np.float32(raw.max()))
    expected_scores = base + expected_bonus
    pred = ranker.predict({"summary": "generic"}, k=44)
    np.testing.assert_array_equal(
        [next(h.score for h in pred.hits if h.uid == uid) for uid in uids],
        expected_scores,
    )
    expected_order = np.lexsort((ranker.uid_array, -expected_scores))
    assert [h.uid for h in pred.hits] == [uids[i] for i in expected_order]

    # The lowest graph contribution was excluded by the old 40-recipient cap.
    notes, used = defaultdict(list), defaultdict(list)
    np.testing.assert_array_equal(
        ranker._structural_bonus(base, np.zeros(44, dtype=np.float32), notes, used),
        expected_bonus,
    )
    assert len(notes) == len(np.flatnonzero(raw))
    assert "generic.f000 -CALLS-> generic.f001" in notes[1][0]
    assert set(pred.support_edges) == {uids[i] for i in np.flatnonzero(raw)}
    for i, uid in enumerate(uids[1:], 1):
        key = (uids[0], "CALLS", uid)
        assert pred.support_edges[uid] == [key]
        assert used[i] == [key]
        assert next(h.path for h in pred.hits if h.uid == uid) != "dense + bm25"
    assert set(pred.traversed) == set(ranker.edges.edges)
    top = ranker.predict({"summary": "generic"}, k=5)
    credit, _, _ = credit_and_debit(top, [uids[1]])
    assert credit == [(uids[0], "CALLS", uids[1])]
    if high_base:
        assert top.hits[1].uid == uids[1]
        assert top.hits[1].score > float(base[1])
        assert "generic.f000 -CALLS-> generic.f001" in top.hits[1].path


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("weights,strongest", [([1.0, 2.0], 1), ([4.0, 2.0], 0)])
def test_only_strongest_contributing_edge_per_recipient_is_supported(live, weights, strongest):
    ranker = make_ranker(5, live)
    uids = ranker.func_uids
    ranker.matrix[1] = [0.6, 0.8]
    ranker.bm25 = SimpleNamespace(score_query=lambda text: {uids[1]: 4.0})
    ranker.bm25_mix = 0.1
    keys = [
        (uids[0], "CALLS", uids[2]),
        (uids[2], "CALLS", uids[1]),
    ]
    for key, weight in zip(keys, weights):
        ranker.edges.ensure(*key, w=weight)
    ranker.edges.ensure(uids[0], "CALLS", uids[3], w=-1.0)
    ranker.edges.ensure(uids[0], "MENTIONS", uids[4], w=100.0)
    pred = ranker.predict({"summary": "generic"}, k=5)
    # Both positive seeds reach only f002, so peak normalization gives it graph_mix.
    expected = ranker.matrix[:, 0].copy()
    expected[1] += np.float32(ranker.bm25_mix)
    expected[2] += np.float32(ranker.graph_mix)
    np.testing.assert_array_equal(
        [next(h.score for h in pred.hits if h.uid == uid) for uid in uids], expected,
    )
    assert pred.support_edges == {uids[2]: [keys[strongest]]}
    assert credit_and_debit(pred, [uids[2]])[0] == [keys[strongest]]
    assert pred.traversed == [keys[strongest]]


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_calls_path_preserves_actual_edge_direction(live, reverse):
    ranker = make_ranker(2, live)
    seed, other = ranker.func_uids
    key = (other, "CALLS", seed) if reverse else (seed, "CALLS", other)
    ranker.edges.ensure(*key, w=1.0)
    pred = ranker.predict({"summary": "generic"}, k=2)
    arrow = "<-CALLS-" if reverse else "-CALLS->"
    assert pred.hits[1].path == f"generic.f000 {arrow} generic.f001 (w 1.00)"
    assert pred.support_edges == {other: [key]}
    assert [h.score for h in pred.hits] == [1.0, float(np.float32(ranker.graph_mix))]
