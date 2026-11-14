import unittest

import numpy as np

from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.dense import DenseIndex
from repocortex.retrieve.frozen import EdgeTable
from repocortex.retrieve.hybrid import HybridRanker
from repocortex.serve.learn import functions_from_diff, learn_from_fix


class ConstEmbedder:
    def encode(self, texts):
        return np.ones((len(texts), 4), dtype=np.float32)

    def encode_one(self, text):
        return np.ones(4, dtype=np.float32)


class FeedbackTest(unittest.TestCase):
    def test_diff_maps_onto_a_function_span(self):
        nodes = {
            "func:q.py:QuerySet.filter": {
                "label": "Function",
                "file": "q.py",
                "qualname": "QuerySet.filter",
                "name": "filter",
                "start": 10,
                "end": 20,
            }
        }
        diff = "\n".join(
            [
                "diff --git a/q.py b/q.py",
                "--- a/q.py",
                "+++ b/q.py",
                "@@ -12,2 +12,3 @@",
                " context",
                "-old",
                "+new",
            ]
        )
        self.assertEqual(functions_from_diff(diff, nodes), ["func:q.py:QuerySet.filter"])

    def test_learn_from_fix_predicts_before_it_stores_the_fix(self):
        nodes = {
            "func:a": {"label": "Function", "name": "filter", "qualname": "QuerySet.filter", "file": "q.py", "signature": "", "doc": "filter", "start": 1, "end": 4},
            "func:b": {"label": "Function", "name": "prefetch_related", "qualname": "QuerySet.prefetch_related", "file": "q.py", "signature": "", "doc": "prefetch", "start": 10, "end": 18},
        }
        matrix = np.array([[1.0, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float32)
        ranker = HybridRanker(
            nodes,
            EdgeTable({}),
            BM25Index.from_nodes(nodes),
            DenseIndex(["func:a", "func:b"], matrix),
            ConstEmbedder(),
            bm25_mix=0.0,
            graph_mix=0.0,
        )
        diff = "+++ b/q.py\n@@ -10,1 +10,2 @@\n context\n+line\n"
        result = learn_from_fix(ranker, "prefetch broken", diff, operators=[])
        self.assertEqual(result["learned"], ["func:b"])
        self.assertEqual(ranker.memory, [])
        operators_result = learn_from_fix(ranker, "prefetch broken again", diff)
        self.assertTrue(ranker.memory)
        self.assertTrue(operators_result["predicted_before"])


if __name__ == "__main__":
    unittest.main()
