"""Setup failures should be actionable before loading an embedding model."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from scripts.preflight import check_database, check_runtime, check_mcp, main


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

    @patch("scripts.preflight.subprocess.run")
    def test_mcp_import_failure_timeout_and_success(self, run):
        run.return_value.returncode = 1
        self.assertFalse(check_mcp())
        self.assertEqual(run.call_args.args[0][-1], "from mcp.server.mcpserver import MCPServer")
        self.assertEqual(run.call_args.kwargs["timeout"], 10)
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["stdout"], subprocess.DEVNULL)
        run.side_effect = subprocess.TimeoutExpired("probe", 10)
        self.assertFalse(check_mcp())
        run.side_effect = OSError("cannot spawn")
        self.assertFalse(check_mcp())
        run.side_effect = None
        run.return_value.returncode = 0
        self.assertTrue(check_mcp())

    def run_main(self, mcp_ok=True):
        output = io.StringIO()
        with patch("sys.argv", ["preflight", "--runtime", str(self.root)]), \
             patch("scripts.preflight.importlib.util.find_spec", return_value=object()), \
             patch("scripts.preflight.check_mcp", return_value=mcp_ok), \
             contextlib.redirect_stdout(output):
            code = main()
        return code, output.getvalue()

    def test_custom_structural_index_remediation(self):
        (self.data / "learned_state.npz").unlink()
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("same repository into a NEW output", output)
        self.assertIn("--embed --runtime", output)
        self.assertIn("Do not mix in Django", output)
        self.assertNotIn("docs/recovery.md", output)

    def test_broken_mcp_dependency_fails_preflight_actionably(self):
        code, output = self.run_main(mcp_ok=False)
        self.assertEqual(code, 1)
        self.assertIn("MCP server dependencies cannot import", output)
        self.assertIn("same virtual-environment Python", output)
        self.assertIn("pip check", output)
        self.assertNotIn("PASS:", output)

    def test_healthy_custom_runtime_passes(self):
        code, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("PASS: runtime artifacts", output)


if __name__ == "__main__":
    unittest.main()
