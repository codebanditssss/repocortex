import copy
import unittest

from scripts.restore_graph import restore, validate_export


class RestoreTest(unittest.TestCase):
    def setUp(self):
        self.payload = {"nodes": [{"id": "a", "label": "Function", "name": "a"},
                                  {"id": "b", "label": "Function", "name": "b"}],
                        "edges": [{"src": "a", "dst": "b", "rel": "CALLS",
                                   "w": 0.0, "hits": 2, "misses": 1}]}

    def test_existing_project_nodes_refused_before_writes(self):
        class Occupied:
            def count_label(self, label):
                return 1
        with self.assertRaisesRegex(ValueError, "existing project nodes"):
            restore(Occupied(), self.payload)

    def test_rejects_dangling_duplicate_and_nonfinite_edges(self):
        for change in (lambda p: p["edges"][0].update(dst="missing"),
                       lambda p: p["edges"].append(dict(p["edges"][0])),
                       lambda p: p["edges"][0].update(w=float("nan"))):
            payload = copy.deepcopy(self.payload)
            change(payload)
            with self.assertRaises(ValueError):
                validate_export(payload)

    def test_restore_preserves_zero_weight_and_checks_counts(self):
        class Empty:
            def upsert_nodes(self, label, rows):
                self.nodes = rows
                return len(rows)
            def upsert_edges(self, rel, rows):
                self.edges = rows
                return len(rows)
            def count_label(self, label):
                return len(getattr(self, "nodes", []))
            def count_rel(self, rel):
                return len(self.edges)
        client = Empty()
        restore(client, self.payload)
        self.assertEqual(client.nodes[0]["uid"], "a")
        self.assertEqual(client.edges[0]["w"], 0.0)
        self.assertEqual(client.edges[0]["hits"], 2)
        self.assertEqual(client.edges[0]["misses"], 1)


if __name__ == "__main__":
    unittest.main()
