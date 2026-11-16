"""Zero edge weights survive persistence and use existing scoring/update formulas."""
from collections import defaultdict
import json
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from repocortex.graph.export import dump_graph, load_corpus
from repocortex.graph.weights import edge_weight
from repocortex.learn.base import Episode
from repocortex.learn.merge import EntityMerger
from repocortex.learn.replay import _snapshot
from repocortex.retrieve.dense import DenseIndex
from repocortex.retrieve.frozen import EdgeTable
from repocortex.retrieve.hybrid import HybridRanker
from repocortex.serve.load import load_ranker

KEY = ('func:a', 'CALLS', 'func:b')


def make_ranker():
    nodes = {uid: {'label': 'Function', 'name': uid, 'qualname': uid, 'file': 'code.py'}
             for uid in ('func:a', 'func:b')}
    embedder = SimpleNamespace(encode_one=lambda text: np.array([1., 0.], dtype=np.float32))
    return HybridRanker(nodes, EdgeTable({KEY: {'w': 0.0}}),
                        SimpleNamespace(score_query=lambda text: {}),
                        DenseIndex(list(nodes), np.eye(2, dtype=np.float32)), embedder,
                        memory_lam=0, shortcut_lam=0, bm25_mix=0)


@pytest.mark.parametrize('props,expected', [({}, 1.), ({'w': None}, 1.), ({'w': 0}, 0.),
                                           ({'w': .5}, .5), ({'w': -1}, -1.)])
def test_weight_decoder_defaults_only_absent_or_null(props, expected):
    assert edge_weight(props) == expected


def test_save_and_loader_roundtrip_preserves_zero_corpus_and_override(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    ranker = make_ranker()
    (data / 'corpus.json').write_text(json.dumps({'nodes': ranker.nodes,
        'edges': [{'src': KEY[0], 'rel': KEY[1], 'dst': KEY[2], 'w': 0.0}]}))
    np.savez(data / 'embeddings.npz', uids=ranker.func_uids, matrix=ranker.matrix)
    ranker.save(data / 'learned_state.npz')
    saved = json.loads((data / 'learned_state.json').read_text())
    assert saved == [{'src': KEY[0], 'rel': KEY[1], 'dst': KEY[2], 'w': 0.,
                      'hits': 0, 'misses': 0, 'tickets': '', 'split': 0}]
    for learned in ([], saved):
        (data / 'learned_state.json').write_text(json.dumps(learned))
        with patch('repocortex.serve.load.Embedder', return_value=ranker.embedder):
            restored = load_ranker(tmp_path)
        assert restored.edges.edges[KEY]['w'] == 0.
    nodes, edges = load_corpus(data / 'corpus.json')
    assert edges[KEY]['w'] == 0.
    dump_graph(nodes, edges, tmp_path / 'export.json')
    assert json.loads((tmp_path / 'export.json').read_text())['edges'][0]['w'] == 0.


def test_zero_adjacency_and_updates_start_from_actual_weight():
    table = EdgeTable({KEY: {'w': 0.0}})
    assert table.undirected(set(KEY[::2]))[KEY[0]] == [(KEY[2], 0.)]
    table.nudge(KEY, reward=1., lr=.25, decay=.08)
    # Original target/decay formula, followed by unchanged .35 floor.
    assert table.edges[KEY]['w'] == pytest.approx(.3905)
    table.edges[KEY]['w'] = 0.
    table.apply_rewards([KEY], {KEY}, lr=.25)
    assert table.edges[KEY]['w'] == .25


def test_zero_flush_and_history_snapshot_are_not_changed_to_one():
    table = EdgeTable({KEY: {'w': 0.0}})
    table.dirty.add(KEY)
    rows = []
    client = SimpleNamespace(update_edge_weights=lambda rel, batch: rows.extend(batch) or len(batch))
    assert table.flush(client) == 1
    assert rows[0]['w'] == 0.
    snapshot = _snapshot(1, {}, {}, SimpleNamespace(edges=table), {})
    assert snapshot['new_edge_count'] == 1
    assert snapshot['new_edges'][0]['w'] == 0.


def test_zero_structural_edge_has_no_bonus_or_evidence_live_and_offline():
    ranker = make_ranker()
    ranker.client = SimpleNamespace(structural_edges=lambda seeds: [(KEY, 0.)])
    for live in (False, True):
        ranker.live_graph = live
        prediction = ranker.predict({'summary': 'a'}, k=2)
        assert [(hit.uid, hit.score) for hit in prediction.hits] == [('func:a', 1.), ('func:b', 0.)]
        assert prediction.support_edges == {}


def test_zero_memory_weight_uses_existing_floor_instead_of_default():
    ranker = make_ranker()
    ranker.memory_lam = 1.
    ranker.memory = [{'uid': 'issue:1', 'ticket': 1, 'golds': ['func:b'],
                      'vec': np.array([1., 0.], dtype=np.float32)}]
    ranker.edges.ensure('issue:1', 'FIXED_IN', 'func:b', w=0.)
    notes, used = defaultdict(list), defaultdict(list)
    ranker._memory_bonus(np.array([1., 0.], dtype=np.float32), notes, used)
    assert '(w 0.85)' in notes[1][0]  # Existing .85 memory floor remains intact.


def test_refinement_inherits_zero_weight_without_resurrection():
    uids = [f'func:pkg/code.py:f{i}' for i in range(10)]
    table = EdgeTable({('concept:broad', 'SHORTCUT', uid): {'w': 0., 'hits': 2, 'misses': 10}
                       for uid in uids})
    ranker = SimpleNamespace(nodes={uid: {'file': 'pkg/code.py'} for uid in uids})
    EntityMerger(ranker=ranker, every=1).on_outcome(table, Episode(ticket=1, seeds=[], gold=[], predicted=[]))
    children = [props for (src, rel, dst), props in table.edges.items()
                if '@' in src and rel == 'SHORTCUT']
    assert len(children) == 10
    assert all(props['w'] == 0. for props in children)


@pytest.mark.parametrize('value,expected', [(0., 0.), (None, 1.), (2.5, 2.5)])
def test_bolt_structural_rows_preserve_zero_and_null_default(value, expected):
    from repocortex.hydradb.base import QueryResult
    from repocortex.hydradb.bolt import BoltClient
    client = BoltClient.__new__(BoltClient)
    client.trace = False

    def query(cypher, params):
        if 'RETURN n.id' in cypher:
            return QueryResult.from_rows([{'id': 1, 'uid': 'func:a'}])
        return QueryResult.from_rows([{'src': KEY[0], 'dst': KEY[2], 'w': value}]
                                     if ':CALLS]' in cypher else [])

    client.query = query
    assert client.structural_edges(['func:a']) == [(KEY, expected)]
