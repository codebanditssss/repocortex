import copy

import numpy as np
import pytest

from repocortex.graph.builder import build_graph
from repocortex.retrieve.hybrid import HybridRanker
from scripts.eval_repository_ablation import evaluate


class Embedder:
    model_name = 'local-test'

    def encode(self, texts):
        return np.tile(np.array([[1., 0.]], dtype=np.float32), (len(texts), 1))

    def encode_one(self, text):
        return self.encode([text])[0]


def dataset():
    return {'issues': [{'ticket': i, 'commit': str(i), 'time': i,
                        'split': 'train' if i < 10 else 'test',
                        'summary': f'unique report {i}', 'description': '',
                        'gold_functions': ['func:app.py:run'], 'gold_files': ['app.py']}
                       for i in range(15)]}


def test_ablation_keeps_outcomes_out_of_holdout_and_does_not_mutate_graph(monkeypatch):
    graph = build_graph([('app.py', 'def run():\n    return 1\n')])
    original = copy.deepcopy(graph)
    original_observe = HybridRanker.observe
    observed = []
    def observe(self, issue):
        assert issue['split'] == 'train'
        observed.append((id(self), issue['ticket']))
        return original_observe(self, issue)
    monkeypatch.setattr(HybridRanker, 'observe', observe)
    result = evaluate(dataset(), graph, Embedder())
    assert result['status'] == 'completed'
    assert len({identity for identity, _ in observed}) == 2
    assert len(observed) == 20
    assert set(result['arms']) == {'text_only', 'frozen_graph', 'flat_fix_memory',
                                  'learned_graph', 'learned_traversal_off'}
    for arm in result['arms'].values():
        assert [r['ticket'] for r in arm['per_issue']] == list(range(10, 15))
    assert graph.nodes == original.nodes
    assert graph.edges == original.edges
    assert len(result['gaps_learned_minus']) == 4


def test_ablation_rejects_overlapping_queries_before_embedding():
    data = dataset()
    data['issues'][-1]['summary'] = data['issues'][0]['summary']
    with pytest.raises(ValueError, match='overlap'):
        evaluate(data, None, Embedder())


def test_frozen_sources_rejects_modified_and_ignored_python(tmp_path):
    import subprocess
    from scripts.eval_repository_ablation import frozen_sources
    def git(*args):
        subprocess.run(['git', '-C', str(tmp_path), *args], check=True, capture_output=True)
    git('init')
    (tmp_path / 'app.py').write_text('def run(): return 1\n')
    (tmp_path / '.gitignore').write_text('hidden.py\n')
    git('add', '.')
    git('-c', 'user.name=test', '-c', 'user.email=test@example.com', 'commit', '-m', 'fixture')
    sources, manifest = frozen_sources(tmp_path, ('.',))
    assert len(sources) == len(manifest) == 1
    (tmp_path / 'app.py').write_text('def run(): return 2\n')
    with pytest.raises(ValueError, match='app.py'):
        frozen_sources(tmp_path, ('.',))
    git('checkout', '--', 'app.py')
    (tmp_path / 'hidden.py').write_text('def unseen(): pass\n')
    with pytest.raises(ValueError, match='hidden.py'):
        frozen_sources(tmp_path, ('.',))
