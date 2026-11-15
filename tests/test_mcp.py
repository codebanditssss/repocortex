import asyncio
import unittest
from unittest.mock import patch

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
                    m.learn_from_fix("bug", "+++ b/a.py")
            state.assert_not_called()

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
