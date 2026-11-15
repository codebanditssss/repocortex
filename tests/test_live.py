import unittest
from unittest.mock import patch
import numpy as np
from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.dense import DenseIndex
from repocortex.retrieve.frozen import EdgeTable
from repocortex.retrieve.hybrid import HybridRanker
from repocortex.serve.load import locate_report

class Embedder:
    def encode_one(self, text):
        return np.array([1., 0.], dtype=np.float32)

class Graph:
    def __init__(self):
        self.target = "func:b"
        self.fail = False
        self.trace = False
        self.last_queries = []
    def ping(self):
        return {"repo": "test", "functions": 3}
    def structural_edges(self, seeds):
        if self.fail:
            raise RuntimeError("database unavailable")
        self.last_queries.append({"cypher": "test traversal", "params": {"seeds": seeds}})
        return [(("func:a", "CALLS", self.target), 1.)]

class LiveTest(unittest.TestCase):
    def ranker(self):
        nodes = {f"func:{x}": {"label":"Function", "name":x, "file":x+".py"} for x in "abc"}
        matrix = np.array([[1.,0.],[0.9,0.],[0.8,0.]], dtype=np.float32)
        return HybridRanker(nodes, EdgeTable({}), BM25Index.from_nodes(nodes),
                            DenseIndex(list(nodes), matrix), Embedder(), client=Graph(),
                            bm25_mix=0., graph_mix=1., memory_lam=0., shortcut_lam=0.)
    def test_database_edges_affect_scores_and_are_not_cached(self):
        r=self.ranker()
        first=locate_report(r,"bug",3)
        r.client.target="func:c"
        second=locate_report(r,"bug",3)
        scores1={h["uid"]:h["score"] for h in first["hits"]}
        scores2={h["uid"]:h["score"] for h in second["hits"]}
        self.assertGreater(scores1["func:b"],scores2["func:b"])
        self.assertGreater(scores2["func:c"],scores1["func:c"])
        self.assertEqual(second["source"],"live")
        self.assertEqual(len(second["queries"]),1)
        self.assertFalse(r.live_graph)
        self.assertFalse(r.client.trace)
    def test_failed_traversal_does_not_claim_live_result(self):
        r=self.ranker();r.client.fail=True
        with self.assertRaises(RuntimeError):locate_report(r,"bug",3)
        self.assertFalse(r.live_graph)
        self.assertFalse(r.client.trace)

    def test_health_failure_refuses_cached_fallback(self):
        for ping in (RuntimeError("offline"), {"repo": "test", "functions": 2}):
            r = self.ranker()
            kwargs = {"side_effect": ping} if isinstance(ping, Exception) else {"return_value": ping}
            with patch.object(r.client, "ping", **kwargs), patch.object(r, "predict") as predict:
                with self.assertRaisesRegex(RuntimeError, "health check failed"):
                    locate_report(r, "bug", 3)
                predict.assert_not_called()

    def test_intentional_replay_remains_available(self):
        r = self.ranker()
        r.client = None
        result = locate_report(r, "bug", 3)
        self.assertEqual(result["source"], "replay")
        self.assertEqual(result["backend"]["mode"], "replay")
        self.assertEqual(len(result["hits"]), 3)

class HttpTest(unittest.TestCase):
    def test_invalid_reports_and_backend_failure_return_json(self):
        import threading, json, urllib.request, urllib.error
        from http.server import ThreadingHTTPServer
        from scripts.serve_locate import make_handler
        ranker=LiveTest().ranker()
        server=ThreadingHTTPServer(("127.0.0.1",0),make_handler(ranker))
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        def post(body, ensure_ascii=True):
            request=urllib.request.Request(f"http://127.0.0.1:{server.server_port}/locate",data=json.dumps(body, ensure_ascii=ensure_ascii).encode(),headers={"Content-Type":"application/json"})
            try:
                with urllib.request.urlopen(request) as response:return response.status,json.load(response)
            except urllib.error.HTTPError as response:
                with response:return response.code,json.load(response)
        try:
            for body in ([],{}, {"report":42},{"report":""}):
                self.assertEqual(post(body)[0],400)
            for report, ascii_encoding in (("错" * 12000, False), ("错" * 12000, True), ("😀" * 12000, False)):
                self.assertEqual(post({"report": report}, ensure_ascii=ascii_encoding)[0], 200)
            self.assertEqual(post({"report": "x" * 12001})[0], 400)
            self.assertEqual(post({"report": "x" * 74000})[0], 413)
            with patch.object(ranker.client, "ping", side_effect=RuntimeError("offline")):
                self.assertEqual(post({"report": "bug"})[0], 503)
            ranker.client.fail=True
            status,payload=post({"report":"bug"})
            self.assertEqual(status,503)
            self.assertEqual(payload["source"],"error")
            self.assertEqual(payload["hits"],[])
        finally:
            server.shutdown();server.server_close();worker.join()
