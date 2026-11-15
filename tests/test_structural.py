import unittest

from repocortex.hydradb.base import QueryResult
from repocortex.hydradb.bolt import BoltClient


class StructuralReadTest(unittest.TestCase):
    def client(self, rows):
        client = BoltClient.__new__(BoltClient)
        client.trace = True
        client.last_queries = []

        def query(cypher, params):
            client.last_queries.append({'cypher': cypher, 'params': params})
            if 'RETURN n.id' in cypher:
                return QueryResult.from_rows([
                    {'id': index + 1, 'uid': uid}
                    for index, uid in enumerate(dict.fromkeys(params['seeds']))
                    if uid != 'func:missing'
                ])
            return QueryResult.from_rows(rows if ':CALLS]' in cypher else [])

        client.query = query
        return client

    def test_shared_seed_edge_counts_once_and_preserves_weight(self):
        client = self.client([{'src': 'func:a', 'dst': 'func:b', 'w': 2.5}])
        self.assertEqual(client.structural_edges(['func:a', 'func:b']),
                         [(('func:a', 'CALLS', 'func:b'), 2.5)])
        self.assertTrue(any('<-[r:CALLS]' in q['cypher'] for q in client.last_queries))
        self.assertTrue(all(q['rows'] == 1 for q in client.last_queries
                            if ':CALLS]' in q['cypher']))
        for receipt in client.last_queries:
            self.assertIs(type(receipt['rows']), int)
            self.assertGreaterEqual(receipt['rows'], 0)
            self.assertIs(type(receipt['limit_reached']), bool)

    def test_missing_seed_refuses_partial_ranking(self):
        client = self.client([])
        with self.assertRaisesRegex(RuntimeError, 'seeds are missing or ambiguous'):
            client.structural_edges(['func:a', 'func:missing'])
        self.assertEqual(len(client.last_queries), 1)
        self.assertEqual(client.last_queries[0]['rows'], 1)
        self.assertFalse(client.last_queries[0]['limit_reached'])

    def test_truncated_adjacency_refuses_partial_results(self):
        client = self.client([{'src': 'func:a', 'dst': f'func:{i}', 'w': 1}
                              for i in range(1000)])
        with self.assertRaisesRegex(RuntimeError, 'refusing partial ranking'):
            client.structural_edges(['func:a'])
        self.assertTrue(client.last_queries[-1]['limit_reached'])

    def test_no_seeds_does_not_query(self):
        client = self.client([])
        self.assertEqual(client.structural_edges([]), [])
        self.assertEqual(client.last_queries, [])
