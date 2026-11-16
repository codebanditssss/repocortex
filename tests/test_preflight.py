"""Setup failures should be actionable before loading an embedding model."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from scripts.preflight import check_database, check_runtime


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        (self.data / "corpus.json").write_text(json.dumps({"nodes": {"func:a": {"label": "Function"}}}))
        (self.data / "learned_state.json").write_text("[]")
        np.savez(self.data / "embeddings.npz", uids=["func:a"], matrix=np.ones((1, 384)))
        self.memory(["func:a"])

    def memory(self, golds):
        np.savez(self.data / "learned_state.npz", tickets=[1],
                 golds=[json.dumps(golds)], vectors=np.ones((1, 384)))

    def test_matching_snapshot(self):
        self.assertEqual(check_runtime(self.root), 1)

    def test_mixed_snapshot_rejected(self):
        self.memory(["func:other"])
        with self.assertRaises(ValueError):
            check_runtime(self.root)

    def test_wrong_embedding_dimensions_rejected(self):
        np.savez(self.data / "embeddings.npz", uids=["func:a"], matrix=np.ones((1, 12)))
        with self.assertRaises(ValueError):
            check_runtime(self.root)

    def test_pickle_arrays_rejected(self):
        np.savez(self.data / "embeddings.npz", uids=np.array(["func:a"], dtype=object), matrix=np.ones((1, 384)))
        with self.assertRaises(ValueError):
            check_runtime(self.root)

    def test_hosted_database_is_rejected_before_connection(self):
        package = self.root / "repocortex"
        package.mkdir()
        (package / "__init__.py").touch()
        (package / "config.py").write_text(
            "from types import SimpleNamespace\nclass Settings:\n"
            "    @staticmethod\n    def load(root): return SimpleNamespace(backend='hosted')\n")
        marker = self.root / "connected"
        (package / "hydradb.py").write_text(
            "from pathlib import Path\ndef connect(settings):\n"
            f"    Path({str(marker)!r}).touch()\n    raise RuntimeError('should not connect')\n")
        self.assertFalse(check_database(self.root, 1))
        self.assertFalse(marker.exists())

    @patch("scripts.preflight.subprocess.run")
    def test_database_probe_is_bounded_and_hides_diagnostics(self, run):
        run.side_effect = subprocess.TimeoutExpired("probe", 15)
        self.assertFalse(check_database(self.root, 1))
        self.assertEqual(run.call_args.kwargs["timeout"], 15)
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["stdout"], subprocess.DEVNULL)

    @patch("scripts.preflight.subprocess.run")
    def test_database_mismatch_fails(self, run):
        run.return_value.returncode = 1
        self.assertFalse(check_database(self.root, 1))


if __name__ == "__main__":
    unittest.main()
