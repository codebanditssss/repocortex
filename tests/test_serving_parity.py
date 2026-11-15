import unittest
from scripts.eval_serving_parity import compare, sample_indices


class ServingParityTest(unittest.TestCase):
    def test_sample_spans_holdout_without_duplicate_rows(self):
        indices = sample_indices(319, 32)
        self.assertEqual((indices[0], indices[-1]), (0, 318))
        self.assertEqual(len(set(indices)), 32)
        self.assertEqual(sample_indices(3, 32), [0, 1, 2])
        with self.assertRaises(ValueError):
            sample_indices(0, 1)

    def test_overlap_does_not_hide_reordered_predictions(self):
        left = [{"uid": "a", "score": 1}, {"uid": "b", "score": .5}]
        right = [{"uid": "b", "score": .6}, {"uid": "a", "score": 1}]
        result = compare(left, right)
        self.assertFalse(result["exact_order"])
        self.assertFalse(result["top1_match"])
        self.assertEqual(result["overlap"], 1)
        self.assertAlmostEqual(result["max_common_score_delta"], .1)

    def test_production_sample_is_fixed_before_requests(self):
        from scripts.eval_production_parity import select_rows
        rows = [{"holdout_index": i} for i in range(32)]
        self.assertEqual([r["holdout_index"] for r in select_rows({"rows": rows})], [0, 4, 8, 13, 17, 22, 26, 31])
        with self.assertRaises(ValueError):
            select_rows({"rows": rows[:-1]})
