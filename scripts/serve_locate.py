"""Small HTTP front for locate_bug. Used by the locust load test."""

from __future__ import annotations

import json
import io
import os
import sys
import time
from threading import BoundedSemaphore
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer as _ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repocortex.serve.load import RankingBusyError, backend_status, load_ranker, locate_report


MAX_REPORT_CHARACTERS = 12000
# JSON can escape each character as six ASCII bytes, plus envelope overhead.
MAX_REQUEST_BYTES = MAX_REPORT_CHARACTERS * 6 + 1024
REQUEST_READ_TIMEOUT = 15


class DeadlineSocketReader(io.RawIOBase):
    """Apply one deadline across request-line, headers and body, even on drips."""
    def __init__(self, connection, timeout):
        super().__init__()
        self.connection = connection
        self.deadline = time.monotonic() + timeout

    def readable(self):
        return True

    def readinto(self, buffer):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("request read deadline exceeded")
        self.connection.settimeout(remaining)
        return self.connection.recv_into(buffer)


class ThreadingHTTPServer(_ThreadingHTTPServer):
    """Bound idle uploads as well as active ranking work."""
    def __init__(self, *args, max_connections=32, **kwargs):
        self._slots = BoundedSemaphore(max_connections)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def read_request_body(stream, connection, length, timeout=15):
    deadline = time.monotonic() + timeout
    chunks = []
    remaining = length
    while remaining:
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("body deadline exceeded")
        connection.settimeout(seconds)
        chunk = stream.read1(min(remaining, 8192))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def make_handler(ranker):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        timeout = 15
        server_version = "RepoCortex"
        sys_version = ""

        def setup(self):
            super().setup()
            self.rfile.close()
            self.rfile = io.BufferedReader(DeadlineSocketReader(self.connection, REQUEST_READ_TIMEOUT))

        def log_message(self, fmt, *args):
            return

        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.close_connection = True
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
            lengths = self.headers.get_all("Content-Length", [])
            if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                self._send(400, {"error": "send one valid content length without transfer encoding"})
                return
            try:
                length = int(lengths[0])
            except ValueError:
                self._send(400, {"error": "invalid content length"})
                return
            if length < 0 or length > MAX_REQUEST_BYTES:
                self._send(413, {"error": "report too large"})
                self.close_connection = True
                return
            try:
                raw = read_request_body(self.rfile, self.connection, length) if length else b"{}"
            except TimeoutError:
                self._send(408, {"error": "request body timed out"})
                return
            if length and len(raw) != length:
                self._send(400, {"error": "incomplete request body"})
                return
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
                self._send(400, {"error": "bad json"})
                return
            if not isinstance(body, dict) or not isinstance(body.get("report"), str):
                self._send(400, {"error": "report must be text"})
                return
            report = body["report"].strip()
            if not report or len(report) > MAX_REPORT_CHARACTERS:
                self._send(400, {"error": "report must contain 1 to 12000 characters"})
                return
            k = body.get("k", 10)
            if type(k) is not int or not 1 <= k <= 20:
                self._send(400, {"error": "k must be an integer from 1 to 20"})
                return
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
