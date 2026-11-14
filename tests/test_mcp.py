import io
import json
import unittest

from scripts.mcp_server import handle, read_message, write_message


class McpTest(unittest.TestCase):
    def test_locate_bug_returns_ranked_hits(self):
        def locate_fn(report, k=10):
            self.assertIn("filter", report)
            self.assertEqual(k, 2)
            return [{"rank": 1, "uid": "func:a", "file": "q.py", "qualname": "QuerySet.filter", "score": 0.5, "path": "dense + bm25"}]

        listed = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, locate_fn)
        self.assertEqual(listed["result"]["tools"][0]["name"], "locate_bug")
        response = handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "locate_bug", "arguments": {"report": "filter rows", "k": 2}},
            },
            locate_fn,
        )
        body = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(body["hits"][0]["uid"], "func:a")
        self.assertIsNone(handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, locate_fn))

    def test_framed_roundtrip(self):
        payload = {"jsonrpc": "2.0", "id": 3, "method": "ping"}
        buf = io.BytesIO()
        write_message(buf, payload)
        buf.seek(0)
        self.assertEqual(read_message(buf), payload)
        response = handle(payload, lambda report, k=10: [])
        self.assertEqual(response["result"], {})


if __name__ == "__main__":
    unittest.main()
