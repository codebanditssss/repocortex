import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import restore_runtime as cli


def corpus():
    return {'nodes': {
        'repo:sample': {'label': 'Repo', 'uid': 'repo:sample', 'name': 'sample'},
        'func:sample.py:answer': {'label': 'Function', 'file': 'sample.py', 'qualname': 'answer',
                                'start': 1, 'end': 3, 'signature': 'value', 'doc': 'Return an answer'}},
        'edges': [{'src': 'repo:sample', 'dst': 'func:sample.py:answer', 'rel': 'CONTAINS', 'w': 1.0}]}


class MemoryClient:
    def __init__(self, feedback=0):
        self.nodes = {}
        self.edges = {}
        self.feedback = feedback
        self.writes = 0
    def query(self, query):
        return SimpleNamespace(rows=[{'n': self.feedback}])
    def count_label(self, label):
        return len(self.nodes.get(label, []))
    def count_rel(self, rel):
        return len(self.edges.get(rel, []))
    def upsert_nodes(self, label, rows):
        self.writes += 1
        self.nodes[label] = rows
        return len(rows)
    def upsert_edges(self, rel, rows):
        self.writes += 1
        self.edges[rel] = rows
        return len(rows)
    def fetch_nodes(self, label):
        return self.nodes[label], False


class RuntimeRestoreTest(unittest.TestCase):
    def test_generic_repo_and_full_node_fields_survive_restore(self):
        client = MemoryClient()
        result = cli.restore_runtime(client, cli.export_from_corpus(corpus()))
        self.assertEqual(result['repository'], 'repo:sample')
        self.assertEqual(result['nodes'], 2)
        self.assertEqual(client.nodes['Function'][0]['doc'], 'Return an answer')
        self.assertEqual(client.nodes['Function'][0]['signature'], 'value')

    def test_existing_graph_or_journal_is_refused_without_writes(self):
        for feedback in (0, 1):
            client = MemoryClient(feedback)
            if not feedback:
                client.nodes['Issue'] = [{'uid': 'existing'}]
            with self.assertRaises(ValueError):
                cli.restore_runtime(client, cli.export_from_corpus(corpus()))
            self.assertEqual(client.writes, 0)

    def test_malformed_corpus_fails_before_ingestion(self):
        mutations = [lambda c: c['nodes']['repo:sample'].update(uid='repo:wrong'),
                     lambda c: c['edges'][0].update(dst='missing'),
                     lambda c: c['edges'][0].update(w=float('nan')),
                     lambda c: c['nodes']['func:sample.py:answer'].update(start=10, end=2),
                     lambda c: c['nodes'].update({'repo:second': {'label': 'Repo'}})]
        for mutation in mutations:
            value = copy.deepcopy(corpus())
            mutation(value)
            with self.assertRaises(ValueError):
                cli.export_from_corpus(value)

    def test_identity_mismatch_fails_even_with_matching_counts(self):
        client = MemoryClient()
        with patch.object(client, 'fetch_nodes', return_value=([{'uid': 'wrong'}], False)):
            with self.assertRaisesRegex(RuntimeError, 'identity verification'):
                cli.restore_runtime(client, cli.export_from_corpus(corpus()))

    def test_validate_only_never_connects(self):
        with TemporaryDirectory() as temp:
            runtime = Path(temp)
            (runtime / 'data').mkdir()
            (runtime / 'data/corpus.json').write_text(json.dumps(corpus()))
            with patch.object(cli, 'connect') as connect:
                self.assertEqual(cli.main(['--runtime', str(runtime)]), 0)
                connect.assert_not_called()

    def test_remote_and_hosted_refused_before_connect(self):
        with TemporaryDirectory() as temp:
            runtime = Path(temp)
            (runtime / 'data').mkdir()
            (runtime / 'data/corpus.json').write_text(json.dumps(corpus()))
            for backend, uri in [('hosted', 'bolt://localhost'), ('bolt', 'bolt://example.com')]:
                with patch.object(cli.Settings, 'load', return_value=SimpleNamespace(backend=backend, bolt_uri=uri)), patch.object(cli, 'connect') as connect:
                    with self.assertRaises(SystemExit):
                        cli.main(['--runtime', str(runtime), '--apply'])
                    connect.assert_not_called()
