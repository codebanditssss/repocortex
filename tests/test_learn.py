import unittest

import numpy as np

from repocortex.eval.metrics import reciprocal_rank
from repocortex.learn.base import Episode
from repocortex.learn.compress import PathCompressor
from repocortex.learn.credit import credit_and_debit
from repocortex.learn.gap import GapIngestor
from repocortex.learn.merge import EntityMerger
from repocortex.learn.replay import replay
from repocortex.learn.reweight import EdgeReweighter
from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.dense import DenseIndex
from repocortex.retrieve.frozen import EdgeTable, Hit, Prediction, gold_paths
from repocortex.retrieve.hybrid import HybridRanker


class ConstEmbedder:
    def encode(self, texts):
        return np.ones((len(texts), 4), dtype=np.float32)

    def encode_one(self, text):
        return np.ones(4, dtype=np.float32)


class CreditTest(unittest.TestCase):
    def test_reweight_ignores_a_spur_off_the_path(self):
        edges = {
            ("s", "CALLS", "gold"): {"w": 1.0, "hits": 0, "misses": 0, "count": 1},
            ("s", "CALLS", "other"): {"w": 1.0, "hits": 0, "misses": 0, "count": 1},
            ("other", "CALLS", "spur"): {"w": 1.0, "hits": 0, "misses": 0, "count": 1},
        }
        table = EdgeTable(edges)
        traversed = list(edges)
        episode = Episode(
            ticket=1,
            seeds=["s"],
            gold=["gold"],
            predicted=["other"],
            traversed=traversed,
        )
        EdgeReweighter(lr=0.5).on_outcome(table, episode)
        self.assertGreater(
            table.edges[("s", "CALLS", "gold")]["w"],
            table.edges[("s", "CALLS", "other")]["w"],
        )
        self.assertEqual(table.edges[("other", "CALLS", "spur")]["w"], 1.0)
        self.assertEqual(table.edges[("other", "CALLS", "spur")]["misses"], 0)
        self.assertNotIn(("other", "CALLS", "spur"), gold_paths(traversed, ["s"], ["other"]))

    def test_debit_does_not_touch_a_hit_dense_already_ranked(self):
        pred = Prediction(
            hits=[Hit("bad", "b.py", 1.0), Hit("gold", "g.py", 0.4), Hit("newbad", "n.py", 0.3)],
            seeds=["s"],
            support_edges={
                "gold": [("issue:1", "FIXED_IN", "gold")],
                "bad": [("issue:1", "FIXED_IN", "bad")],
                "newbad": [("issue:2", "SHORTCUT", "newbad")],
            },
            base_topk=["bad", "gold"],
        )
        credit, debit, promoted = credit_and_debit(pred, ["gold"])
        self.assertEqual(credit, [("issue:1", "FIXED_IN", "gold")])
        self.assertEqual(debit, [("issue:2", "SHORTCUT", "newbad")])
        self.assertEqual(promoted, ["newbad"])

    def test_repeated_debit_stays_in_range(self):
        table = EdgeTable({("s", "CALLS", "t"): {"w": 1.0, "hits": 0, "misses": 0, "count": 1}})
        for _ in range(25):
            table.nudge(("s", "CALLS", "t"), 0.0)
        weight = table.edges[("s", "CALLS", "t")]["w"]
        self.assertGreaterEqual(weight, 0.35)
        self.assertLess(weight, 1.0)


class OperatorTest(unittest.TestCase):
    def test_shortcut_waits_for_support(self):
        table = EdgeTable({})
        compressor = PathCompressor(min_support=3, min_precision=0.4)
        for ticket in (1, 2):
            compressor.on_outcome(
                table,
                Episode(ticket=ticket, seeds=[], gold=["func:b"], predicted=[], concepts=["concept:prefetch"]),
            )
        self.assertNotIn(("concept:prefetch", "SHORTCUT", "func:b"), table.edges)
        compressor.on_outcome(
            table,
            Episode(ticket=3, seeds=[], gold=["func:b"], predicted=[], concepts=["concept:prefetch"]),
        )
        edge = table.edges[("concept:prefetch", "SHORTCUT", "func:b")]
        self.assertGreaterEqual(edge["hits"], 3)
        self.assertGreaterEqual(edge["w"], 0.4)
        self.assertIn("3", edge["tickets"])

    def test_gap_links_a_missed_function(self):
        nodes = {
            "func:gold": {
                "label": "Function",
                "file": "django/db/models/query.py",
                "name": "prefetch_related",
                "qualname": "QuerySet.prefetch_related",
            },
            "func:near": {"label": "Function", "file": "django/db/models/query.py", "name": "filter"},
            "test:t": {"label": "Test", "name": "test_prefetch_related"},
        }
        table = EdgeTable({})
        episode = Episode(
            ticket=9,
            seeds=["func:near"],
            gold=["func:gold"],
            predicted=["func:near"],
            frontier=["func:near"],
            gap_concepts=["concept:prefetch"],
        )
        result = GapIngestor(nodes=nodes).on_outcome(table, episode)
        self.assertGreater(result.applied, 0)
        self.assertIn(("func:near", "CO_CHANGED", "func:gold"), table.edges)
        self.assertIn(("func:gold", "TESTED_BY", "test:t"), table.edges)
        self.assertIn("concept:prefetch", episode.concepts)

    def test_merge_links_concepts_with_the_same_targets(self):
        table = EdgeTable({})
        for src in ("concept:a", "concept:b"):
            for index in range(3):
                table.ensure(src, "SHORTCUT", f"func:{index}", replace=True, hits=3, misses=0, learned=1)
        result = EntityMerger(every=1).on_outcome(table, Episode(ticket=1, seeds=[], gold=[], predicted=[]))
        self.assertGreater(result.applied, 0)
        self.assertIn(("concept:a", "SAME_AS", "concept:b"), table.edges)


class HybridTest(unittest.TestCase):
    def _ranker(self, **kwargs):
        nodes = {
            "func:a": {"label": "Function", "name": "filter", "qualname": "QuerySet.filter", "file": "q.py", "signature": "", "doc": "filter rows"},
            "func:b": {"label": "Function", "name": "prefetch_related", "qualname": "QuerySet.prefetch_related", "file": "q.py", "signature": "", "doc": "prefetch cache"},
            "func:c": {"label": "Function", "name": "clean", "qualname": "Form.clean", "file": "f.py", "signature": "", "doc": "clean form"},
            "concept:prefetch": {"label": "Concept", "name": "prefetch"},
        }
        matrix = np.array(
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.2, 0.2, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
            ],
            dtype=np.float32,
        )
        dense = DenseIndex(["func:a", "func:b", "func:c"], matrix)
        return HybridRanker(
            nodes,
            EdgeTable({}),
            BM25Index.from_nodes(nodes),
            dense,
            ConstEmbedder(),
            client=None,
            bm25_mix=0.0,
            memory_lam=0.5,
            shortcut_lam=0.5,
            **kwargs,
        )

    def test_step_zero_matches_dense_order(self):
        ranker = self._ranker()
        issue = {"ticket": 1, "summary": "prefetch cache", "description": "", "gold_functions": ["func:b"], "gold_files": ["q.py"]}
        pred = ranker.predict(issue, k=3)
        vector = np.ones(4, dtype=np.float32)
        vector /= np.linalg.norm(vector)
        dense_order = np.lexsort((np.array(ranker.func_uids), -(ranker.matrix @ vector)))
        self.assertEqual([hit.uid for hit in pred.hits], [ranker.func_uids[int(i)] for i in dense_order])

    def test_replay_raises_mrr_for_a_repeated_fix(self):
        ranker = self._ranker()
        def issue(ticket, split):
            return {
                "ticket": ticket,
                "summary": "prefetch cache bug",
                "description": "prefetch related cache",
                "gold_functions": ["func:b"],
                "gold_files": ["q.py"],
                "split": split,
            }
        train = [issue(n, "train") for n in (1, 2, 3)]
        holdout = [issue(9, "test")]
        played = replay(ranker, train, holdout, every=10)
        self.assertGreater(played["curve"][-1]["mrr"], played["curve"][0]["mrr"])
        self.assertGreater(reciprocal_rank(["func:b"], ["func:b"]), played["curve"][0]["mrr"])
        self.assertIn(("concept:prefetch", "SHORTCUT", "func:b"), ranker.edges.edges)
        self.assertIn(("issue:1", "FIXED_IN", "func:b"), ranker.edges.edges)


if __name__ == "__main__":
    unittest.main()
