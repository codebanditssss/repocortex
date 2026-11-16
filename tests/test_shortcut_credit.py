from repocortex.learn.base import Episode
from repocortex.learn.compress import PathCompressor
from repocortex.retrieve.frozen import EdgeTable


def episode(**kwargs):
    return Episode(ticket=9, seeds=[], gold=['gold'], predicted=['gold'], **kwargs)


def test_refined_child_success_preserves_inherited_counts_and_restart():
    table = EdgeTable({})
    child = ('concept:word@module', 'SHORTCUT', 'gold')
    table.ensure(*child, hits=3, misses=2, count=3, tickets='1,2,3', w=0.6)
    compressor = PathCompressor()
    compressor.on_outcome(table, episode(concepts=['concept:word'], credit=[child]))
    assert {k: table.edges[child][k] for k in ('hits', 'misses', 'tickets')} == {
        'hits': 4, 'misses': 2, 'tickets': '1,2,3,9'}
    assert table.edges[child]['w'] == 0.6667
    restarted = PathCompressor()
    restarted.hydrate(table)
    restarted.on_outcome(table, Episode(ticket=10, seeds=[], gold=['gold'], predicted=['gold'], credit=[child]))
    assert table.edges[child]['hits'] == 5
    assert table.edges[child]['misses'] == 2
    assert table.edges[child]['tickets'] == '1,2,3,9,10'


def test_lexical_and_repeated_credit_count_same_pair_once():
    table = EdgeTable({})
    key = ('concept:word', 'SHORTCUT', 'gold')
    table.ensure(*key, hits=3, misses=0, tickets='1,2,3')
    PathCompressor().on_outcome(table, episode(concepts=['concept:word', 'concept:word'], credit=[key, key]))
    assert table.edges[key]['hits'] == 4
    assert table.edges[key]['tickets'] == '1,2,3,9'


def test_credit_never_invents_shortcuts_or_rewards_wrong_targets():
    table = EdgeTable({})
    wrong = ('concept:word', 'SHORTCUT', 'wrong')
    call = ('caller', 'CALLS', 'gold')
    table.ensure(*wrong, hits=3, misses=0)
    table.ensure(*call, w=1)
    before = {key: dict(value) for key, value in table.edges.items()}
    PathCompressor().on_outcome(table, episode(credit=[wrong, call, ('absent', 'SHORTCUT', 'gold')]))
    assert table.edges == before


def test_real_prediction_credits_child_created_by_split():
    import numpy as np
    from repocortex.learn.merge import EntityMerger
    from repocortex.learn.replay import learn_one
    from repocortex.retrieve.bm25 import BM25Index
    from repocortex.retrieve.dense import DenseIndex
    from repocortex.retrieve.hybrid import HybridRanker

    class Embedder:
        def encode_one(self, text):
            return np.array([1., 0.], dtype=np.float32)

    uids = [f'func:pkg/mod{i // 2}/code.py:f{i}' for i in range(12)]
    nodes = {u: {'label': 'Function', 'name': f'f{i}', 'qualname': f'f{i}',
                 'file': u.split(':')[1], 'doc': '', 'signature': ''} for i, u in enumerate(uids)}
    nodes['concept:widget'] = {'label': 'Concept', 'name': 'widget'}
    table = EdgeTable({})
    for i, uid in enumerate(uids):
        table.ensure('concept:widget', 'SHORTCUT', uid, hits=3,
                     misses=0 if i < 2 else 20, tickets='1,2,3')
    matrix = np.array([[1., 0.]] + [[0., 1.]] * 11, dtype=np.float32)
    ranker = HybridRanker(nodes, table, BM25Index.from_nodes(nodes), DenseIndex(uids, matrix), Embedder())
    EntityMerger(ranker=ranker, every=1).on_outcome(table, Episode(ticket=4, seeds=[], gold=[], predicted=[]))
    child = ('concept:widget@pkg.mod0', 'SHORTCUT', uids[0])
    assert table.edges[child]['hits'] == 3
    pred, _ = learn_one(ranker, {'ticket': 9, 'summary': 'widget fails', 'description': '',
                               'gold_functions': [uids[0]], 'gold_files': ['pkg/mod0/code.py']},
                        [PathCompressor()])
    assert 'concept:widget@pkg.mod0' not in pred.concepts
    assert child in pred.support_edges[uids[0]]
    assert table.edges[child]['hits'] == 4
