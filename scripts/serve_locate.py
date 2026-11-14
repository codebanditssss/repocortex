"""Small HTTP front for locate_bug. Used by the locust load test."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repocortex.serve.load import load_ranker, locate


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
            self._send(200, {"status": "ok"})

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/locate":
                self._send(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._send(400, {"error": "bad json"})
                return
            report = str(body.get("report") or "")
            try:
                k = int(body.get("k") or 10)
            except (TypeError, ValueError):
                k = 10
            self._send(200, {"hits": locate(ranker, report, k)})

    return Handler


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    ranker = load_ranker(root)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(ranker))
    print(f"listening http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
