import json
import unittest

import httpx

from repocortex.hydradb.hosted import HostedClient


class HostedRequestTest(unittest.TestCase):
    def test_byog_body_and_headers(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers["Authorization"]
            seen["version"] = request.headers["API-Version"]
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(
                200,
                json={"success": True, "data": [{"n": 2}], "error": None, "meta": {"request_id": "r1"}},
            )

        client = HostedClient("https://api.hydradb.com", "test-key", "repocortex", "code")
        client._client = httpx.Client(transport=httpx.MockTransport(handler), headers=client._client.headers)
        result = client.query("MATCH (n:Function) RETURN count(n) AS n", {"limit": 10})
        self.assertEqual(result.rows, [{"n": 2}])
        self.assertEqual(seen["auth"], "Bearer test-key")
        self.assertEqual(seen["version"], "2")
        self.assertEqual(seen["body"]["database"], "repocortex")
        self.assertEqual(seen["body"]["collection"], "code")
        self.assertEqual(seen["body"]["params"], {"limit": 10})
        self.assertIn("MATCH", seen["body"]["query"])
        client.close()


if __name__ == "__main__":
    unittest.main()
