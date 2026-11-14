import unittest

import numpy as np

from repocortex.eval.metrics import bootstrap_ci, bootstrap_gap
from repocortex.graph.builder import build_graph
from repocortex.learn.replay import checkpoint_steps, replay
from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.dense import DenseIndex
from repocortex.retrieve.frozen import EdgeTable
from repocortex.retrieve.hybrid import HybridRanker


class ConstEmbedder:
    def encode(self, texts):
        return np.ones((len(texts), 4), dtype=np.float32)

    def encode_one(self, text):
        return np.ones(4, dtype=np.float32)


class ScaleTest(unittest.TestCase):
    def test_bootstrap_interval_covers_the_mean(self):
        samples = []
        for index in range(40):
            hit = float(index % 2 == 0)
            samples.append(
                {
                    "ticket": index,
                    "function_acc@5": hit,
                    "function_acc@10": hit,
                    "file_acc@1": hit,
                    "file_acc@5": hit,
                    "mrr": hit,
                }
            )
        ci = bootstrap_ci(samples, n_boot=200, seed=1)
        self.assertEqual(ci["function_acc@10"]["mean"], 0.5)
        self.assertLessEqual(ci["function_acc@10"]["lo"], 0.5)
        self.assertGreaterEqual(ci["function_acc@10"]["hi"], 0.5)

    def test_paired_gap_is_positive_when_learned_wins(self):
        learned = []
        baseline = []
        for index in range(30):
            learned.append(
                {
                    "ticket": index,
                    "function_acc@5": 1.0,
                    "function_acc@10": 1.0,
                    "file_acc@1": 1.0,
                    "file_acc@5": 1.0,
                    "mrr": 1.0,
                }
            )
            baseline.append(
                {
                    "ticket": index,
                    "function_acc@5": 0.0,
                    "function_acc@10": 0.0,
                    "file_acc@1": 0.0,
                    "file_acc@5": 0.0,
                    "mrr": 0.0,
                }
            )
        gap = bootstrap_gap(learned, baseline, n_boot=100, seed=2)
        self.assertEqual(gap["n"], 30)
        self.assertEqual(gap["mrr"]["mean"], 1.0)
        self.assertGreater(gap["function_acc@10"]["lo"], 0.0)

    def test_checkpoint_steps_include_ends(self):
        steps = checkpoint_steps(1400, 15)
        self.assertEqual(steps[0], 0)
        self.assertEqual(steps[-1], 1400)
        self.assertGreaterEqual(len(steps), 14)
        self.assertEqual(len(steps), len(set(steps)))

    def test_learning_disabled_is_flat_and_matches_step_zero(self):
        nodes = {
            "func:a": {"label": "Function", "name": "filter", "qualname": "QuerySet.filter", "file": "q.py", "signature": "", "doc": "filter"},
            "func:b": {"label": "Function", "name": "prefetch_related", "qualname": "QuerySet.prefetch_related", "file": "q.py", "signature": "", "doc": "prefetch"},
            "concept:prefetch": {"label": "Concept", "name": "prefetch"},
        }
        matrix = np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]], dtype=np.float32)
        dense = DenseIndex(["func:a", "func:b"], matrix)

        def issue(ticket):
            return {
                "ticket": ticket,
                "summary": "prefetch cache",
                "description": "",
                "gold_functions": ["func:b"],
                "gold_files": ["q.py"],
                "time": ticket,
            }

        def ranker():
            return HybridRanker(
                {uid: dict(node) for uid, node in nodes.items()},
                EdgeTable({}),
                BM25Index.from_nodes(nodes),
                dense,
                ConstEmbedder(),
                bm25_mix=0.0,
                graph_mix=0.0,
                memory_lam=0.5,
            )

        train = [issue(1), issue(2)]
        holdout = [issue(9)]
        disabled = replay(ranker(), train, holdout, points=5, mode="disabled")
        self.assertEqual(
            [row["function_acc@10"] for row in disabled["curve"]],
            [disabled["curve"][0]["function_acc@10"]] * len(disabled["curve"]),
        )
        full = replay(ranker(), train, holdout, points=5, mode="full")
        self.assertEqual(full["curve"][0]["mrr"], disabled["curve"][0]["mrr"])
        self.assertGreater(full["curve"][-1]["mrr"], full["curve"][0]["mrr"])

    def test_class_attribute_call_from_a_test_is_tested_by(self):
        src = "class QuerySet:\n    def filter(self):\n        return 1\n"
        test = "class QueryTests(TestCase):\n    def test_filter(self):\n        QuerySet.filter()\n"
        graph = build_graph(
            [
                ("django/db/models/query.py", src),
                ("tests/queries/tests.py", test),
            ]
        )
        self.assertTrue(any(edge.rel == "TESTED_BY" for edge in graph.edges.values()))


if __name__ == "__main__":
    unittest.main()
