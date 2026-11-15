import unittest
from unittest.mock import patch
import numpy as np
from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.dense import DenseIndex
from repocortex.retrieve.frozen import EdgeTable
from repocortex.retrieve.hybrid import HybridRanker
from repocortex.serve.load import RankingBusyError, locate_report

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

    def test_busy_ranker_expires_without_starting_work(self):
        import threading
        r = self.ranker()
        acquired, release = threading.Event(), threading.Event()
        def hold_ranker():
            with r.request_lock:
                acquired.set()
                release.wait(2)
        worker = threading.Thread(target=hold_ranker)
        worker.start()
        self.assertTrue(acquired.wait(1))
        try:
            with patch("repocortex.serve.load.REQUEST_LOCK_TIMEOUT_SECONDS", 0.01), patch.object(r, "predict") as predict:
                with self.assertRaises(RankingBusyError):
                    locate_report(r, "bug", 3)
                predict.assert_not_called()
        finally:
            release.set()
            worker.join()
        # Timed-out callers must neither release another request's lock nor poison it.
        self.assertEqual(len(locate_report(r, "bug", 3)["hits"]), 3)

    def test_health_error_releases_lock_for_other_threads(self):
        import threading
        r = self.ranker()
        with patch.object(r.client, "ping", side_effect=RuntimeError("offline")):
            with self.assertRaises(RuntimeError):
                locate_report(r, "bug", 3)
        acquired = []
        def check():
            locked = r.request_lock.acquire(timeout=0.1)
            acquired.append(locked)
            if locked:
                r.request_lock.release()
        worker = threading.Thread(target=check)
        worker.start(); worker.join()
        self.assertEqual(acquired, [True])

class HttpTest(unittest.TestCase):
    def test_failed_feedback_marks_health_degraded_even_with_reachable_database(self):
        from repocortex.serve.load import backend_status
        ranker = LiveTest().ranker()
        ranker.feedback_failed = True
        with patch.object(ranker.client, "ping") as ping:
            result = backend_status(ranker)
        self.assertEqual(result["mode"], "error")
        self.assertFalse(result["connected"])
        self.assertIn("recovery required", result["detail"])
        ping.assert_not_called()

    def test_health_does_not_expose_connection_errors(self):
        from repocortex.serve.load import backend_status
        ranker = LiveTest().ranker()
        with patch.object(ranker.client, "ping", side_effect=RuntimeError("secret-token@private-host")):
            result = backend_status(ranker)
        self.assertEqual(result["mode"], "error")
        self.assertNotIn("secret", str(result))
        self.assertNotIn("private-host", str(result))

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
            for k in (0, -1, 21, True, 1.5, "10", None):
                self.assertEqual(post({"report": "bug", "k": k})[0], 400)
            import socket
            for framing in ("Content-Length: 2\r\nContent-Length: 2", "Content-Length: 2\r\nTransfer-Encoding: chunked", "Content-Length: +2"):
                with socket.create_connection(server.server_address, timeout=2) as sock:
                    sock.sendall(("POST /locate HTTP/1.1\r\nHost: localhost\r\n" + framing + "\r\n\r\n{}").encode())
                    response = sock.recv(4096)
                    self.assertIn(b"400 Bad Request", response)
                    self.assertIn(b"Connection: close", response)
            for report, ascii_encoding in (("错" * 12000, False), ("错" * 12000, True), ("😀" * 12000, False)):
                self.assertEqual(post({"report": report}, ensure_ascii=ascii_encoding)[0], 200)
            self.assertEqual(post({"report": "x" * 12001})[0], 400)
            self.assertEqual(post({"report": "x" * 74000})[0], 413)
            with patch.object(ranker.client, "ping", side_effect=RuntimeError("offline")):
                self.assertEqual(post({"report": "bug"})[0], 503)
            with patch("scripts.serve_locate.locate_report", side_effect=RankingBusyError("busy")):
                status, payload = post({"report": "bug"})
                self.assertEqual(status, 503)
                self.assertIn("busy", payload["error"])
                self.assertEqual(payload["hits"], [])
            ranker.client.fail=True
            status,payload=post({"report":"bug"})
            self.assertEqual(status,503)
            self.assertEqual(payload["source"],"error")
            self.assertEqual(payload["hits"],[])
        finally:
            server.shutdown();server.server_close();worker.join()
