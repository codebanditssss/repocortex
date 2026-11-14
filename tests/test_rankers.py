import unittest

from repocortex.eval.metrics import file_hit, function_hit, reciprocal_rank, summarize
from repocortex.mine.commits import hunk_lines
from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.ppr import personalized_pagerank
from repocortex.retrieve.frozen import EdgeTable, gold_paths
from repocortex.learn.base import Episode
from repocortex.learn.reweight import EdgeReweighter


class MetricsTest(unittest.TestCase):
    def test_strict_function_acc(self):
        self.assertEqual(function_hit(["a", "b", "c"], ["c", "a"], 3), 1)
        self.assertEqual(function_hit(["a", "b", "c"], ["c", "a"], 2), 0)
        self.assertEqual(file_hit(["f.py", "f.py", "g.py"], ["g.py"], 1), 0)
        self.assertEqual(file_hit(["f.py", "f.py", "g.py"], ["g.py"], 2), 1)
        self.assertEqual(file_hit(["f.py", "g.py"], ["g.py", "f.py"], 2), 1)
        self.assertAlmostEqual(reciprocal_rank(["x", "a"], ["a"]), 0.5)

    def test_summary(self):
        stats = summarize(
            [
                {
                    "ranked": ["a", "b"],
                    "files": ["a.py", "b.py"],
                    "gold": ["a"],
                    "gold_files": ["a.py"],
                }
            ]
        )
        self.assertEqual(stats["function_acc@5"], 1.0)
        self.assertEqual(stats["mrr"], 1.0)


class HunkTest(unittest.TestCase):
    def test_hunk_lines(self):
        diff = "@@ -10,2 +12,3 @@\n@@ -40 +50,0 @@\n@@ -8,0 +9 @@\n"
        new_lines, old_lines = hunk_lines(diff)
        self.assertEqual(new_lines, [12, 13, 14, 9])
        self.assertEqual(old_lines, [10, 11, 40])


class RankTest(unittest.TestCase):
    def test_bm25_prefers_the_matching_doc(self):
        nodes = {
            "func:a": {"label": "Function", "qualname": "QuerySet.filter", "name": "filter", "file": "q.py", "signature": "", "doc": "filter rows"},
            "func:b": {"label": "Function", "qualname": "Form.clean", "name": "clean", "file": "f.py", "signature": "", "doc": "validate a form"},
        }
        index = BM25Index.from_nodes(nodes)
        top = index.top("filter queryset rows", 1)
        self.assertEqual(top[0][0], "func:a")

    def test_ppr_stays_near_the_seed(self):
        nodes = ["a", "b", "c"]
        adj = {"a": [("b", 1.0)], "b": [("a", 1.0), ("c", 0.1)], "c": [("b", 0.1)]}
        rank = personalized_pagerank(nodes, adj, {"a": 1.0}, teleport=0.2, iterations=30)
        self.assertGreater(rank["a"], rank["c"])

    def test_reweight_moves_a_good_edge_above_a_bad_one(self):
        edges = {
            ("s", "CALLS", "gold"): {"w": 1.0, "hits": 0, "misses": 0, "count": 1},
            ("s", "CALLS", "other"): {"w": 1.0, "hits": 0, "misses": 0, "count": 1},
        }
        table = EdgeTable(edges)
        episode = Episode(
            ticket=1,
            seeds=["s"],
            gold=["gold"],
            predicted=["other"],
            traversed=[("s", "CALLS", "gold"), ("s", "CALLS", "other")],
        )
        EdgeReweighter(lr=0.5).on_outcome(table, episode)
        self.assertGreater(table.edges[("s", "CALLS", "gold")]["w"], table.edges[("s", "CALLS", "other")]["w"])
        self.assertEqual(table.edges[("s", "CALLS", "gold")]["hits"], 1)
        self.assertEqual(table.edges[("s", "CALLS", "other")]["misses"], 1)
        self.assertIn(("s", "CALLS", "gold"), gold_paths(episode.traversed, ["s"], ["gold"]))


if __name__ == "__main__":
    unittest.main()
