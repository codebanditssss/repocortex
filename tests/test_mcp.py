import asyncio
import unittest

from scripts.mcp_server import server


class McpTest(unittest.TestCase):
    def test_tools_are_registered(self):
        tools = asyncio.run(server.list_tools())
        names = sorted(tool.name for tool in tools)
        self.assertEqual(names, ["learn_from_fix", "locate_bug"])
        locate = next(tool for tool in tools if tool.name == "locate_bug")
        self.assertIn("report", locate.input_schema["properties"])
        learn = next(tool for tool in tools if tool.name == "learn_from_fix")
        self.assertIn("diff", learn.input_schema["properties"])


if __name__ == "__main__":
    unittest.main()
