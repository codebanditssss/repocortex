import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.mcp_server import server


class McpTest(unittest.TestCase):
    def test_untrusted_feedback_and_invalid_inputs_do_not_load_ranker(self):
        from scripts import mcp_server as m
        with patch.object(m, "get_state") as state:
            for report in ("", "x" * 12001):
                with self.assertRaises(ValueError):
                    m.locate_bug(report)
            with self.assertRaises(ValueError):
                m.locate_bug("bug", True)
            with self.assertRaises(ValueError):
                m.learn_from_fix("bug", "x" * 256001)
            with patch.object(m, "_http_mode", True):
                with self.assertRaises(ValueError):
                    m.learn_from_fix("bug", "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n")
            state.assert_not_called()

    def test_feedback_without_journal_never_applies_or_writes_base(self):
        from scripts import mcp_server as m
        for journal_present in (False, True):
            with self.subTest(journal_attribute_present=journal_present), TemporaryDirectory() as directory:
                root = Path(directory)
                base = root / "data" / "learned_state.npz"
                base.parent.mkdir()
                base.write_bytes(b"original runtime")
                ranker = SimpleNamespace(request_lock=Mock(), flush=Mock(), save=Mock())
                if journal_present:
                    ranker.feedback_journal = None
                state = {"ranker": ranker, "operators": [], "root": root}
                with patch.object(m, "_http_mode", False), patch.object(m, "get_state", return_value=state), patch("repocortex.serve.learn.learn_from_fix") as apply_fix:
                    with self.assertRaisesRegex(ValueError, "REPOCORTEX_FEEDBACK_NAMESPACE"):
                        m.learn_from_fix("a valid bug report", "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n")
                apply_fix.assert_not_called()
                ranker.request_lock.acquire.assert_not_called()
                ranker.flush.assert_not_called()
                ranker.save.assert_not_called()
                self.assertEqual(base.read_bytes(), b"original runtime")

    def test_namespaced_feedback_never_passes_shared_snapshot_path(self):
        from scripts import mcp_server as m
        ranker = SimpleNamespace(feedback_journal=object(), request_lock=Mock(), n=2, nodes={},
                                 client=SimpleNamespace(ping=lambda: {"repo": "repo:fixture", "functions": 2}))
        state = {"ranker": ranker, "operators": []}
        with patch.object(m, "_http_mode", False), patch.object(m, "get_state", return_value=state), patch("repocortex.serve.learn.learn_from_fix", return_value={"learned": ["function"]}) as apply_fix:
            self.assertEqual(m.learn_from_fix("bug", "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n"), {"learned": ["function"]})
        apply_fix.assert_called_once_with(ranker, "bug", "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n", operators=[])
        ranker.request_lock.release.assert_called_once()

    def test_wrong_repository_refuses_feedback_under_lock(self):
        from scripts import mcp_server as m
        ranker = SimpleNamespace(feedback_journal=object(), request_lock=Mock(), n=2,
                                 nodes={"repo:httpx": {"label": "Repo"}},
                                 client=SimpleNamespace(ping=lambda: {"repo": "repo:django", "functions": 2}))
        with patch.object(m, "_http_mode", False), patch.object(m, "get_state", return_value={"ranker": ranker, "operators": []}), patch("repocortex.serve.learn.learn_from_fix") as apply_fix:
            with self.assertRaisesRegex(RuntimeError, "matching this runtime"):
                m.learn_from_fix("bug", "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n")
        apply_fix.assert_not_called()
        ranker.request_lock.acquire.assert_called_once()
        ranker.request_lock.release.assert_called_once()

    def test_database_loss_after_startup_refuses_feedback(self):
        from scripts import mcp_server as m
        client = Mock()
        client.ping.side_effect = RuntimeError("connection lost")
        ranker = SimpleNamespace(feedback_journal=object(), request_lock=Mock(), n=2,
                                 nodes={"repo:httpx": {"label": "Repo"}}, client=client)
        with patch.object(m, "get_state", return_value={"ranker": ranker, "operators": []}), patch("repocortex.serve.learn.learn_from_fix") as apply_fix:
            with self.assertRaisesRegex(RuntimeError, "no feedback was written"):
                m.learn_from_fix("bug", "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n")
        apply_fix.assert_not_called()
        ranker.request_lock.release.assert_called_once()

    def test_wrong_repository_refuses_namespaced_startup_before_journal(self):
        from scripts import mcp_server as m
        client = Mock()
        client.ping.return_value = {"repo": "repo:django", "functions": 2}
        ranker = SimpleNamespace(n=2, nodes={"repo:httpx": {"label": "Repo"}})
        with patch.object(m, "_state", None), patch.dict(m.os.environ, {"REPOCORTEX_FEEDBACK_NAMESPACE": "isolated-httpx"}), patch("repocortex.serve.load.load_ranker", return_value=ranker), patch("repocortex.learn.replay.make_operators", return_value=[]), patch("repocortex.config.Settings.load", return_value=SimpleNamespace(backend="bolt")), patch("repocortex.hydradb.connect", return_value=client), patch("repocortex.serve.feedback.configure_feedback") as configure:
            with self.assertRaisesRegex(RuntimeError, "matching this runtime"):
                m._load_state()
        configure.assert_not_called()
        client.close.assert_called_once()

    def test_namespaced_hosted_startup_refused_before_connection(self):
        from scripts import mcp_server as m
        with patch.object(m, "_state", None), patch.dict(m.os.environ, {"REPOCORTEX_FEEDBACK_NAMESPACE": "pilot"}), patch("repocortex.serve.load.load_ranker", return_value=SimpleNamespace()), patch("repocortex.learn.replay.make_operators", return_value=[]), patch("repocortex.config.Settings.load", return_value=SimpleNamespace(backend="hosted")), patch("repocortex.hydradb.connect") as connect:
            with self.assertRaisesRegex(ValueError, "Bolt backend"):
                m._load_state()
        connect.assert_not_called()

    def test_tools_are_registered(self):
        tools = asyncio.run(server.list_tools())
        names = sorted(tool.name for tool in tools)
        self.assertEqual(names, ["graph_status", "learn_from_fix", "locate_bug"])
        locate = next(tool for tool in tools if tool.name == "locate_bug")
        self.assertIn("report", locate.input_schema["properties"])
        learn = next(tool for tool in tools if tool.name == "learn_from_fix")
        self.assertIn("diff", learn.input_schema["properties"])


if __name__ == "__main__":
    unittest.main()
