import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from scripts import feedback_cli as cli


class FeedbackCLITest(TestCase):
    def setUp(self):
        self.ranker = SimpleNamespace(nodes={"func:example.py:fixed": {
            "label": "Function", "file": "example.py", "qualname": "fixed", "start": 10, "end": 20}},
            feedback_journal=SimpleNamespace(fingerprint="base-one"))
        self.diff = "--- a/example.py\n+++ b/example.py\n@@ -12 +12 @@\n-old\n+fixed\n"
        self.report = "Unicode parsing fails"

    def test_preview_never_learns_or_searches(self):
        with patch.object(cli, "learn_from_fix") as learn, patch.object(cli, "locate_report") as locate:
            result = cli.execute(self.ranker, "preview", "pilot", self.report, self.diff)
        self.assertFalse(result["writes"])
        self.assertEqual(result["matched_functions"][0]["uid"], "func:example.py:fixed")
        learn.assert_not_called()
        locate.assert_not_called()

    def test_changed_review_inputs_reject_before_write(self):
        token = cli.review(self.ranker, "pilot", self.report, self.diff)["review_token"]
        for namespace, report, diff in [("other", self.report, self.diff),
                                       ("pilot", "different", self.diff),
                                       ("pilot", self.report, self.diff + "\n")]:
            with self.subTest(namespace=namespace, report=report, diff=diff), patch.object(cli, "learn_from_fix") as learn:
                with self.assertRaisesRegex(ValueError, "preview again"):
                    cli.execute(self.ranker, "apply", namespace, report, diff, token)
                learn.assert_not_called()
        self.ranker.feedback_journal.fingerprint = "different-base"
        with self.assertRaisesRegex(ValueError, "preview again"):
            cli.execute(self.ranker, "apply", "pilot", self.report, self.diff, token)

    def test_apply_returns_before_after_and_duplicate_receipt(self):
        token = cli.review(self.ranker, "pilot", self.report, self.diff)["review_token"]
        outcome = {"learned": ["func:example.py:fixed"], "skipped": "already learned"}
        with patch.object(cli, "learn_from_fix", return_value=outcome) as learn, \
             patch.object(cli, "locate_report", side_effect=[{"hits": ["before"]}, {"hits": ["after"]}]):
            receipt = cli.execute(self.ranker, "apply", "pilot", self.report, self.diff, token)
        learn.assert_called_once_with(self.ranker, self.report, self.diff)
        self.assertEqual(receipt["feedback"], outcome)
        self.assertEqual(receipt["after"], {"hits": ["after"]})
        self.assertTrue(receipt["retained"])

    def test_unmatched_diff_cannot_apply(self):
        with patch.object(cli, "learn_from_fix") as learn:
            with self.assertRaisesRegex(ValueError, "no changed functions"):
                cli.execute(self.ranker, "apply", "pilot", self.report, self.diff.replace("example.py", "absent.py"), "token")
            learn.assert_not_called()

    def test_invalid_namespace_and_missing_confirmation_fail_before_loading(self):
        with patch.object(cli, "load_ranker") as load:
            for args in [["search", "--namespace", "bad namespace", "--report", "report.txt"],
                         ["apply", "--namespace", "pilot", "--report", "report.txt", "--diff", "fix.diff"]]:
                with self.assertRaises(SystemExit):
                    cli.main(args)
            load.assert_not_called()

    def test_existing_receipt_is_not_overwritten(self):
        with TemporaryDirectory() as temp, patch.object(cli, "load_ranker") as load:
            target = Path(temp) / "receipt.json"
            target.write_text("existing")
            with self.assertRaises(SystemExit):
                cli.main(["search", "--namespace", "pilot", "--report", "r.txt", "--output", str(target)])
            self.assertEqual(target.read_text(), "existing")
            load.assert_not_called()

    def test_unwritable_receipt_fails_before_loading(self):
        with TemporaryDirectory() as temp, patch.object(cli, "load_ranker") as load:
            root = Path(temp)
            report = root / "report.txt"
            report.write_text(self.report)
            obstacle = root / "file"
            obstacle.write_text("not a directory")
            with self.assertRaises(SystemExit):
                cli.main(["search", "--namespace", "pilot", "--report", str(report), "--output", str(obstacle / "receipt.json")])
            load.assert_not_called()

    def test_connection_failure_does_not_fall_back_to_replay(self):
        with TemporaryDirectory() as temp, patch.object(cli, "load_ranker", return_value=self.ranker), \
             patch.object(cli.Settings, "load", return_value=SimpleNamespace(backend="bolt")), patch.object(cli, "connect", side_effect=RuntimeError("private details")), \
             patch.object(cli, "execute") as execute:
            report = Path(temp) / "report.txt"
            report.write_text(self.report)
            with self.assertRaises(SystemExit):
                cli.main(["search", "--namespace", "pilot", "--report", str(report)])
            execute.assert_not_called()

    def test_input_limits_and_empty_files(self):
        with TemporaryDirectory() as temp:
            report = Path(temp) / "report.txt"
            for content in [" " , "abcdef"]:
                report.write_text(content)
                with self.assertRaises(ValueError):
                    cli.read_input(report, 4, "report")

    def test_failed_startup_leaves_explicit_incomplete_receipt(self):
        with TemporaryDirectory() as temp, patch.object(cli, "load_ranker", side_effect=RuntimeError("missing runtime")):
            root = Path(temp)
            report, receipt = root / "report.txt", root / "receipt.json"
            report.write_text(self.report)
            with self.assertRaises(SystemExit):
                cli.main(["search", "--namespace", "pilot", "--report", str(report), "--output", str(receipt)])
            self.assertEqual(json.loads(receipt.read_text())["status"], "incomplete")

    def test_receipt_under_runtime_directory_is_rejected(self):
        with patch.object(cli, "load_ranker") as load:
            with self.assertRaises(SystemExit):
                cli.main(["search", "--namespace", "pilot", "--report", "r.txt",
                          "--output", str(cli.ROOT / "data" / "receipt.json")])
            load.assert_not_called()

    def test_hosted_backend_rejected_before_loading_or_connecting(self):
        with TemporaryDirectory() as temp, \
             patch.object(cli.Settings, "load", return_value=SimpleNamespace(backend="hosted")), \
             patch.object(cli, "load_ranker") as load, patch.object(cli, "connect") as connect:
            report = Path(temp) / "report.txt"
            receipt = Path(temp) / "receipt.json"
            report.write_text(self.report)
            with self.assertRaises(SystemExit):
                cli.main(["search", "--namespace", "pilot", "--report", str(report), "--output", str(receipt)])
            load.assert_not_called()
            connect.assert_not_called()
            self.assertFalse(receipt.exists())
