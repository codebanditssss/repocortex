from repocortex.learn.compress import PathCompressor
from repocortex.serve.learn import learn_from_fix
from scripts.verify_persistent_learning import fixture_ranker


DIFF = '--- a/fixture.py\n+++ b/fixture.py\n@@ -10 +10 @@\n-old\n+fixed{}\n'
KEY = ('concept:widget', 'SHORTCUT', 'func:fixture.py:beta')


def local_ranker():
    r = fixture_ranker()
    r.add_node('concept:widget', 'Concept', 'widget')
    return r


def test_default_operators_accumulate_and_duplicate_fix_is_noop():
    r = local_ranker()
    for i in range(4):
        learn_from_fix(r, f'widget case {i}', DIFF.format(i))
    assert r.edges.edges[KEY]['hits'] == 4
    operators = r.feedback_operators
    before = dict(r.edges.edges[KEY])
    result = learn_from_fix(r, 'widget case 3', DIFF.format(3))
    assert result['skipped']
    assert r.edges.edges[KEY] == before
    assert len(r.memory) == 4
    assert r.feedback_operators is operators


def test_operator_state_is_per_ranker_and_explicit_operators_are_respected():
    first, second = local_ranker(), local_ranker()
    learn_from_fix(first, 'widget first', DIFF.format(0))
    learn_from_fix(second, 'widget second', DIFF.format(1))
    assert first.feedback_operators is not second.feedback_operators
    for r in (first, second):
        compressor = next(op for op in r.feedback_operators if isinstance(op, PathCompressor))
        assert compressor.hits[(KEY[0], KEY[2])] == 1
    explicit = []
    third = local_ranker()
    learn_from_fix(third, 'widget explicit', DIFF.format(2), operators=explicit)
    assert not getattr(third, 'feedback_operators', None)
    assert not third.memory


def test_fresh_operator_hydrates_materialized_edge_support():
    r = local_ranker()
    r.edges.ensure(*KEY, hits=4, misses=2, count=4, tickets='1,2,3,4', w=0.6667)
    learn_from_fix(r, 'widget another fix', DIFF.format(5))
    assert r.edges.edges[KEY]['hits'] == 5
    assert r.edges.edges[KEY]['misses'] == 2
