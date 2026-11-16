"""Compare text, graph and past-fix memory on one frozen repository dataset.

Offline retrospective evaluation. No parameter search, production writes or
external model calls. The same queries and candidate functions serve every arm.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from repocortex.eval.harness import eval_ranker
from repocortex.graph.builder import build_graph, iter_sources
from repocortex.learn.replay import replay
from repocortex.mine.commits import snapshot_sha
from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.dense import Embedder, build_dense_index
from repocortex.retrieve.frozen import EdgeTable
from repocortex.retrieve.hybrid import HybridRanker, QueryCache
from scripts.eval_lexical import paired_gap
from scripts.eval_transfer import split_audit


def frozen_sources(repo, scope):
    """Verify the actual indexed text against HEAD, including ignored files."""
    sources = iter_sources(repo, scope)
    manifest = []
    for name, source in sources:
        stored = subprocess.run(['git', '-C', str(repo), 'show', f'HEAD:{name}'],
                                capture_output=True, check=False)
        if stored.returncode or stored.stdout.decode('utf-8', errors='replace') != source:
            raise ValueError(f'indexed source differs from snapshot: {name}')
        manifest.append({'path': name, 'sha256': hashlib.sha256(source.encode()).hexdigest()})
    return sources, manifest


def evaluate(dataset, graph, embedder=None):
    audit = split_audit(dataset)
    train = sorted((r for r in dataset['issues'] if r['split'] == 'train'),
                   key=lambda r: (r['time'], r['ticket']))
    test = sorted((r for r in dataset['issues'] if r['split'] == 'test'),
                  key=lambda r: (r['time'], r['ticket']))
    if len(train) < 10 or len(test) < 5:
        return {'status': 'insufficient_sample', 'split_audit': audit}
    nodes = {uid: node.as_row() | {'label': node.label} for uid, node in graph.nodes.items()}
    edges = {key: edge.as_row() for key, edge in graph.edges.items()}
    embedder = embedder or Embedder()
    dense = build_dense_index(nodes, embedder)
    bm25 = BM25Index.from_nodes(nodes)
    cache = QueryCache()
    vectors = {}

    def fresh():
        ranker = HybridRanker({u: dict(n) for u, n in nodes.items()},
                              EdgeTable({k: dict(v) for k, v in edges.items()}),
                              bm25, dense, embedder, client=None)
        ranker.score_cache = cache
        ranker._vec = vectors  # Immutable query embeddings only; no labels or outcomes.
        return ranker

    text = fresh()
    text.graph_mix = text.shortcut_lam = text.memory_lam = 0.0
    frozen = fresh()
    flat = fresh()
    flat.graph_mix = flat.shortcut_lam = 0.0
    # All training outcomes are available before the frozen test period. This
    # baseline retrieves prior reports without structural/shortcut traversal.
    flat.prepare(train)
    for issue in train:
        flat.observe(issue)
    learned = fresh()
    played = replay(learned, train, test, mode='full', points=5)
    wanted = {int(r['ticket']) for r in train}
    for ranker in (flat, learned):
        if {int(r['ticket']) for r in ranker.memory} != wanted:
            raise RuntimeError('memory does not match the training split')
    metrics = {}
    for name, ranker in [('text_only', text), ('frozen_graph', frozen),
                         ('flat_fix_memory', flat), ('learned_graph', learned)]:
        print(name, flush=True)
        metrics[name] = eval_ranker(ranker, test)
    # Match the full learned state exactly; disable only graph/shortcut scoring.
    graph_mix, shortcut_lam = learned.graph_mix, learned.shortcut_lam
    try:
        learned.graph_mix = learned.shortcut_lam = 0.0
        metrics['learned_traversal_off'] = eval_ranker(learned, test)
    finally:
        learned.graph_mix, learned.shortcut_lam = graph_mix, shortcut_lam
    return {
        'status': 'completed', 'split_audit': audit,
        'functions': len(dense.uids), 'arms': metrics,
        'distinct_commits': {split: len({r['commit'] for r in rows})
                             for split, rows in [('train', train), ('test', test)]},
        'operators': played['operators'], 'params': played['params'], 'curve': played['curve'],
        'gaps_learned_minus': {name: paired_gap(metrics['learned_graph']['per_issue'], value['per_issue'])
                               for name, value in metrics.items() if name != 'learned_graph'},
        'methodology': {
            'execution': 'offline in-memory graph, no HydraDB queries; not live deployment evidence',
            'parameters': 'unchanged defaults; no calibration or selection on this dataset',
            'flat_fix_memory': 'same prior report embeddings and fix labels, no traversal or graph operators; unit FIXED_IN weights',
            'learned_traversal_off': 'identical learned memory including learned FIXED_IN weights; structural and shortcut score terms disabled only for evaluation',
            'limitations': ['Retrospective final source snapshot may contain later fixes.',
                            'Current issue bodies may contain later edits.',
                            'Mapped changed functions proxy fault location.',
                            'Cross-split query and commit overlap checked; semantic duplicates not detected.',
                            'Accuracy is strict: all changed functions must be in the first ten results.',
                            'MRR is truncated to ten candidates (MRR@10).',
                            'Issue-level bootstrap intervals are exploratory: reports can share a fix commit.'],
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('--out already exists; choose a fresh evidence file')
    raw = args.dataset.read_bytes()
    dataset = json.loads(raw)
    if snapshot_sha(args.repo) != dataset['snapshot']:
        parser.error('checkout does not match dataset snapshot')
    sources, source_manifest = frozen_sources(args.repo, tuple(dataset['scope']))
    graph = build_graph(sources)
    root = Path(__file__).resolve().parents[1]
    code_manifest = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted((root / 'repocortex').rglob('*.py'))}
    for name in ('eval_repository_ablation.py', 'eval_transfer.py', 'eval_lexical.py'):
        p = root / 'scripts' / name
        code_manifest[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    evaluator_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result = evaluate(dataset, graph)
    result.update(repository=dataset['repository'], snapshot=dataset['snapshot'],
                  dataset_sha256=hashlib.sha256(raw).hexdigest(),
                  evaluator_sha256=evaluator_hash, source_manifest=source_manifest,
                  code_manifest=code_manifest,
                  source_manifest_sha256=hashlib.sha256(json.dumps(source_manifest, sort_keys=True).encode()).hexdigest())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x') as output:
        output.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps({name: {'function_acc@10': m['function_acc@10'], 'mrr': m['mrr']}
                      for name, m in result.get('arms', {}).items()}), flush=True)


if __name__ == '__main__':
    main()
