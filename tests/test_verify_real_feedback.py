"""The runnable feedback check must preserve runtime and clean up on failure."""
import argparse
from contextlib import redirect_stdout
import io
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from repocortex.config import Settings
from scripts import verify_real_feedback as verify


class RealFeedbackCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        (self.root / "data/dataset.json").write_text(json.dumps({"issues": [
            {"ticket": 37442, "commit": "a" * 40, "gold_functions": ["fn"]}
        ]}))
        self.args = argparse.Namespace(ticket=37442, diff=self.root / "fix.diff",
                                       fetch_diff=True, output=None, phase=None, namespace=None)

    def response(self, body=b"confirmed diff"):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = body
        return response

    def test_mismatched_diff_cannot_connect_or_write(self):
        self.args.fetch_diff = False
        self.args.diff.write_text("different diff")
        with patch.object(verify.Settings, "load", return_value=Settings()), \
                patch.object(verify, "urlopen", return_value=self.response()), \
                patch.object(verify, "connect") as connect:
            with self.assertRaisesRegex(ValueError, "does not match"):
                verify.run_verification(self.args, self.root)
        connect.assert_not_called()

    def test_failed_worker_still_cleans_namespace_and_closes_database(self):
        client = MagicMock()
        with patch.object(verify.Settings, "load", return_value=Settings()), \
                patch.object(verify, "urlopen", return_value=self.response()), \
                patch.object(verify, "connect", return_value=client), \
                patch.object(verify, "hashes", return_value={}), \
                patch.object(verify, "counts", return_value={}), \
                patch.object(verify.subprocess, "run", return_value=MagicMock(returncode=1)) as run:
            with self.assertRaisesRegex(RuntimeError, "cached locally"):
                verify.run_verification(self.args, self.root)
        self.assertEqual(self.args.diff.read_bytes(), b"confirmed diff")
        self.assertEqual(run.call_args.kwargs["timeout"], 300)
        self.assertEqual(run.call_args.kwargs["env"]["HF_HUB_OFFLINE"], "1")
        cleanup = client.query.call_args
        self.assertIn("DETACH DELETE", cleanup.args[0])
        self.assertTrue(cleanup.args[1]["namespace"].startswith("verify-real-"))
        client.close.assert_called_once()

    def test_timed_out_worker_also_cleans_namespace(self):
        client = MagicMock()
        with patch.object(verify.Settings, "load", return_value=Settings()), \
                patch.object(verify, "urlopen", return_value=self.response()), \
                patch.object(verify, "connect", return_value=client), \
                patch.object(verify, "hashes", return_value={}), \
                patch.object(verify, "counts", return_value={}), \
                patch.object(verify.subprocess, "run", side_effect=subprocess.TimeoutExpired("worker", 300)):
            with self.assertRaises(subprocess.TimeoutExpired):
                verify.run_verification(self.args, self.root)
        self.assertIn("DETACH DELETE", client.query.call_args.args[0])
        client.close.assert_called_once()

    def test_existing_receipt_is_not_overwritten(self):
        receipt = self.root / "receipt.json"
        receipt.write_text("previous evidence")
        with patch.object(verify.sys, "argv", ["verify", "--fetch-diff", "--output", str(receipt)]), \
                patch.object(verify, "run_verification") as run, \
                patch.object(Path, "is_file", return_value=True):
            with self.assertRaises(SystemExit) as error:
                verify.main()
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(receipt.read_text(), "previous evidence")
        run.assert_not_called()

    def test_remote_database_is_refused_before_download(self):
        with patch.object(verify.Settings, "load", return_value=Settings(bolt_uri="bolt://example.com:7687")), \
                patch.object(verify, "urlopen") as download:
            with self.assertRaisesRegex(SystemExit, "remote databases are refused"):
                verify.run_verification(self.args, self.root)
        download.assert_not_called()

    def test_summary_uses_observed_ranks_without_promising_improvement(self):
        result = {"ticket": 1, "report_summary": "report", "checks": {"restart": True},
                  "processes": [{"mapped_functions": [{"uid": "fn", "qualname": "target"}],
                                 "before": [], "after": [{"uid": "fn", "rank": 4}]},
                                {"before": [{"uid": "fn", "rank": 4}]}]}
        output = io.StringIO()
        with redirect_stdout(output):
            verify.print_summary(result, Path("work/evidence.json"))
        self.assertIn("outside top 10 -> 4 -> 4 after restart", output.getvalue())
        self.assertIn("not an accuracy benchmark", output.getvalue())
        self.assertIn("PASS: restart", output.getvalue())

    def test_output_cannot_overwrite_runtime(self):
        with patch.object(verify.sys, "argv", ["verify", "--fetch-diff", "--output", str(Path(verify.__file__).resolve().parents[1] / "data/corpus.json")]), \
                patch.object(verify, "run_verification") as run, \
                patch.object(Path, "is_file", return_value=True):
            with self.assertRaises(SystemExit) as error:
                verify.main()
        self.assertEqual(error.exception.code, 2)
        run.assert_not_called()
