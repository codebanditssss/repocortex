"""Failure boundaries and process-independent feedback reconstruction."""
import copy
import unittest
from unittest.mock import patch

from repocortex.hydradb.base import QueryResult
from repocortex.serve.feedback import FeedbackJournal, configure_feedback, feedback_ticket
from repocortex.serve.learn import learn_from_fix
from repocortex.serve.load import locate, locate_report
from scripts.verify_persistent_learning import fixture_ranker, REPORT, DIFF


class JournalClient:
    def __init__(self):
        self.records = {}
        self.fail_write = False

    def query(self, cypher, params=None):
        if cypher.startswith("UNWIND"):
            params = params["rows"][0]
            if self.fail_write:
                raise RuntimeError("unavailable")
            self.records[params["id"]] = copy.deepcopy(params)
            return QueryResult.from_rows([])
        if "WHERE n.namespace" in cypher:
            records = sorted((r for r in self.records.values() if r["namespace"] == params["namespace"]), key=lambda r: r["sequence"])
            return QueryResult.from_rows(records[params["skip"]:params["skip"] + 500])
        found = self.records.get(params["id"])
        return QueryResult.from_rows([found] if found else [])


class PersistentFeedbackTest(unittest.TestCase):
    def test_restart_recovers_and_duplicate_does_not_change_ranking(self):
        client = JournalClient()
        first = fixture_ranker(client)
        configure_feedback(first, "test")
        before = locate(first, REPORT)
        outcome = learn_from_fix(first, REPORT, DIFF)
        after = locate(first, REPORT)
        self.assertNotEqual(before[0]["uid"], after[0]["uid"])
        self.assertEqual(outcome["persistence"], "hydradb feedback journal")
        second = fixture_ranker(client)
        configure_feedback(second, "test")
        self.assertEqual(after, locate(second, REPORT))
        self.assertTrue(learn_from_fix(second, REPORT, DIFF)["skipped"])
        self.assertEqual(len(second.memory), 1)
        unrelated = fixture_ranker(client)
        configure_feedback(unrelated, "other")
        self.assertEqual(unrelated.memory, [])

    def test_restart_retains_support_before_shortcut_is_materialized(self):
        def ranker(client):
            result = fixture_ranker(client)
            result.add_node("concept:widget", "Concept", "widget")
            return result

        def apply(result, number):
            return learn_from_fix(result, f"widget confirmed case {number}",
                                  DIFF.replace("+fixed", f"+fixed{number}"))

        client = JournalClient()
        uninterrupted = ranker(client)
        configure_feedback(uninterrupted, "subthreshold")
        key = ("concept:widget", "SHORTCUT", "func:fixture.py:beta")
        for number in range(2):
            apply(uninterrupted, number)
        self.assertNotIn(key, uninterrupted.edges.edges)

        restarted = ranker(client)
        setup = configure_feedback(restarted, "subthreshold")
        self.assertEqual(setup["replayed"], 2)
        self.assertNotIn(key, restarted.edges.edges)
        self.assertTrue(apply(restarted, 1)["skipped"])
        self.assertEqual(len(restarted.memory), 2)
        self.assertEqual(len(client.records), 2)
        self.assertNotIn(key, restarted.edges.edges)

        apply(uninterrupted, 2)
        apply(restarted, 2)
        self.assertEqual(restarted.edges.edges[key], uninterrupted.edges.edges[key])
        self.assertEqual(restarted.edges.edges[key]["hits"], 3)
        self.assertEqual(len(restarted.memory), 3)
        self.assertEqual(len(client.records), 3)

    def test_failed_journal_write_does_not_apply_fix(self):
        client = JournalClient()
        ranker = fixture_ranker(client)
        configure_feedback(ranker, "test")
        client.fail_write = True
        with self.assertRaises(RuntimeError):
            learn_from_fix(ranker, REPORT, DIFF)
        self.assertEqual(ranker.memory, [])
        self.assertEqual(ranker.edges.edges, {})

    def test_crash_after_commit_before_application_is_recovered(self):
        client = JournalClient()
        ranker = fixture_ranker(client)
        configure_feedback(ranker, "test")
        with patch("repocortex.learn.replay.learn_one", side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):
                learn_from_fix(ranker, REPORT, DIFF)
        with self.assertRaisesRegex(RuntimeError, "restart"):
            learn_from_fix(ranker, REPORT, DIFF)
        with self.assertRaisesRegex(RuntimeError, "restart"):
            locate_report(ranker, REPORT)
        restarted = fixture_ranker(client)
        configure_feedback(restarted, "test")
        self.assertEqual(len(restarted.memory), 1)
        self.assertEqual(locate(restarted, REPORT)[0]["uid"], "func:fixture.py:beta")

    def test_changed_base_snapshot_is_rejected(self):
        client = JournalClient()
        first = fixture_ranker(client)
        configure_feedback(first, "test")
        learn_from_fix(first, REPORT, DIFF)
        changed = fixture_ranker(client)
        changed.nodes["func:fixture.py:beta"]["start"] = 9
        with self.assertRaisesRegex(ValueError, "different base snapshot"):
            configure_feedback(changed, "test")

    def test_missing_database_fails_closed(self):
        with self.assertRaises(RuntimeError):
            configure_feedback(fixture_ranker(), "test")

    def test_ticket_identity_has_no_delimiter_ambiguity(self):
        self.assertNotEqual(feedback_ticket("a\nb", "c"), feedback_ticket("a", "b\nc"))

    def test_invalid_namespace_is_rejected(self):
        with self.assertRaises(ValueError):
            FeedbackJournal(JournalClient(), "bad' namespace")


if __name__ == "__main__":
    unittest.main()
