"""The published mechanism demo exercises persistence without external services."""
import unittest

from scripts.demo_feedback import run_demo


class FeedbackDemoTest(unittest.TestCase):
    def test_confirmed_fix_survives_reload_and_duplicate_is_skipped(self):
        result = run_demo()
        self.assertFalse(result["database_connected"])
        self.assertEqual(result["before"]["memory_entries"], 0)
        self.assertEqual(result["after"]["memory_entries"], 1)
        self.assertEqual(result["after"], result["reloaded"])
        self.assertEqual(result["after"]["hits"][0]["uid"], result["feedback"]["learned"][0])
        self.assertEqual(result["saved"]["learned_edges"], 1)
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual(result, run_demo(), "the fixture output must be reproducible")
