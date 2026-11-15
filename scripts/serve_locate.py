"""Small HTTP front for locate_bug. Used by the locust load test."""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repocortex.serve.load import RankingBusyError, backend_status, load_ranker, locate_report


MAX_REPORT_CHARACTERS = 12000
# JSON can escape each character as six ASCII bytes, plus envelope overhead.
MAX_REQUEST_BYTES = MAX_REPORT_CHARACTERS * 6 + 1024


def make_handler(ranker):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            return

        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.split("?", 1)[0] != "/health":
                self._send(404, {"error": "not found"})
                return
            payload = {"status": "ok"}
            payload.update(backend_status(ranker))
            healthy = payload.get("mode") != "error"
            payload["status"] = "ok" if healthy else "degraded"
            self._send(200 if healthy else 503, payload)

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/locate":
                self._send(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._send(400, {"error": "invalid content length"})
                return
            if length < 0 or length > MAX_REQUEST_BYTES:
                self._send(413, {"error": "report too large"})
                self.close_connection = True
                return
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send(400, {"error": "bad json"})
                return
            if not isinstance(body, dict) or not isinstance(body.get("report"), str):
                self._send(400, {"error": "report must be text"})
                return
            report = body["report"].strip()
            if not report or len(report) > MAX_REPORT_CHARACTERS:
                self._send(400, {"error": "report must contain 1 to 12000 characters"})
                return
            try:
                k = int(body.get("k") or 10)
            except (TypeError, ValueError):
                k = 10
            try:
                payload = locate_report(ranker, report, k)
            except RankingBusyError:
                self._send(503, {"error": "ranking is busy; try again shortly", "source": "error",
                                 "hits": [], "queries": []})
                return
            except Exception:
                self._send(503, {"error": "ranking unavailable", "source": "error",
                                 "hits": [], "queries": [],
                                 "backend": {"mode": "error", "connected": False,
                                             "detail": "graph query or ranking failed"}})
                return
            self._send(200, payload)

    return Handler


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8765"))
    host = os.environ.get("HOST", "127.0.0.1")
    ranker = load_ranker(root)
    try:
        from repocortex.config import Settings
        from repocortex.hydradb import connect

        ranker.client = connect(Settings.load(root))
    except Exception:
        ranker.client = None
    server = ThreadingHTTPServer((host, port), make_handler(ranker))
    print(f"listening http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
