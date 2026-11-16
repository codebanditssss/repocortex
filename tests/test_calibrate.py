from types import SimpleNamespace

import pytest

from repocortex.learn import calibrate


def rows(n=30):
    return [{"ticket": i, "commit": str(i // 2), "time": i // 2,
             "split": "train"} for i in range(n)]


def test_split_keeps_commits_together_and_rejects_holdout():
    fit, validation = calibrate.calibration_split(list(reversed(rows())))
    assert {r['commit'] for r in fit}.isdisjoint(r['commit'] for r in validation)
    assert max(r['time'] for r in fit) <= min(r['time'] for r in validation)
    with pytest.raises(ValueError, match='training rows only'):
        calibrate.calibration_split(rows() + [{"split": "test"}])
    with pytest.raises(ValueError, match='unique'):
        calibrate.calibration_split(rows() + [rows()[0]])


def test_selection_uses_only_fit_feedback_and_default_wins_ties(monkeypatch):
    fit, validation = calibrate.calibration_split(rows())
    factories = []
    def factory():
        ranker = SimpleNamespace(memory=[])
        factories.append(ranker)
        return ranker
    def replay(ranker, training, holdout, **kwargs):
        assert training == fit
        assert holdout == []
        ranker.memory = [{"ticket": r['ticket']} for r in training]
    def evaluate(ranker, tested):
        assert tested == validation
        assert {r['ticket'] for r in ranker.memory}.isdisjoint(r['ticket'] for r in tested)
        return {'function_acc@10': .5, 'mrr': .4, 'per_issue': []}
    monkeypatch.setattr(calibrate, 'replay', replay)
    monkeypatch.setattr(calibrate, 'eval_ranker', evaluate)
    result = calibrate.calibrate_memory(rows(), factory)
    assert result['selected'] == {'memory_lam': .08}
    assert len(factories) == 5
    monkeypatch.setattr(calibrate, 'eval_ranker', lambda ranker, _: {
        'function_acc@10': 1 if ranker.memory_lam == .16 else 0,
        'mrr': 0, 'per_issue': []})
    assert calibrate.calibrate_memory(rows(), factory)['selected'] == {'memory_lam': .16}
    monkeypatch.setattr(calibrate, 'eval_ranker', lambda ranker, _: {
        'function_acc@10': .5, 'mrr': .9 if ranker.memory_lam == .04 else .1,
        'per_issue': []})
    assert calibrate.calibrate_memory(rows(), factory)['selected'] == {'memory_lam': .04}


def test_small_sample_does_not_fit_any_candidate():
    def factory():
        raise AssertionError('not enough evidence to calibrate')
    result = calibrate.calibrate_memory(rows(12), factory)
    assert result['status'] == 'insufficient_sample'
    assert result['selected'] == {'memory_lam': .08}


def test_contaminated_memory_is_rejected(monkeypatch):
    monkeypatch.setattr(calibrate, 'replay', lambda ranker, *args, **kwargs: ranker.memory.append({'ticket': -1}))
    with pytest.raises(RuntimeError, match='only fit tickets'):
        calibrate.calibrate_memory(rows(), lambda: SimpleNamespace(memory=[]))


def test_duplicate_queries_across_inner_split_are_rejected():
    data = rows()
    data[0]['summary'] = 'Connection FAILED'
    data[-1]['summary'] = ' connection   failed '
    with pytest.raises(ValueError, match='query overlaps'):
        calibrate.calibration_split(data)
