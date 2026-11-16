"""Small HTTP front for locate_bug. Used by the locust load test."""

from __future__ import annotations

import json
import io
import hmac
import ipaddress
import math
import os
import sys
import time
from threading import BoundedSemaphore, Lock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer as _ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repocortex.serve.load import RankingBusyError, backend_status, load_ranker, locate_report, runtime_directory


MAX_REPORT_CHARACTERS = 12000
# A non-BMP character can use a 12-byte escaped JSON surrogate pair.
MAX_REQUEST_BYTES = MAX_REPORT_CHARACTERS * 12 + 1024
REQUEST_READ_TIMEOUT = 15
DEFAULT_RATE_LIMIT_PER_MINUTE = 30
MAX_RATE_LIMIT_CLIENTS = 4096
TRUSTED_CLIENT_IP_HEADER = "X-RepoCortex-Client-IP"


class FixedWindowRateLimiter:
    """Bounded, thread-safe request counter keyed by client identity."""

    def __init__(self, limit: int, window_seconds: int = 60, max_clients: int = MAX_RATE_LIMIT_CLIENTS):
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self._clients: dict[str, tuple[float, int, float]] = {}
        self._lock = Lock()

    def allow(self, client: str, now: float | None = None) -> tuple[bool, int]:
        current = time.monotonic() if now is None else now
        with self._lock:
            record = self._clients.get(client)
            if record is None or current - record[0] >= self.window_seconds:
                if record is None and len(self._clients) >= self.max_clients:
                    expired = [key for key, value in self._clients.items()
                               if current - value[0] >= self.window_seconds]
                    for key in expired:
                        self._clients.pop(key, None)
                    if len(self._clients) >= self.max_clients:
                        oldest = min(self._clients, key=lambda key: self._clients[key][2])
                        self._clients.pop(oldest, None)
                self._clients[client] = (current, 1, current)
                return True, 0
            started, count, _ = record
            retry_after = max(1, math.ceil(self.window_seconds - (current - started)))
            if count >= self.limit:
                self._clients[client] = (started, count, current)
                return False, retry_after
            self._clients[client] = (started, count + 1, current)
            return True, 0


def _peer_ip(handler) -> str:
    address = getattr(handler, "client_address", None)
    if isinstance(address, tuple) and address:
        return str(address[0])
    try:
        return str(handler.connection.getpeername()[0])
    except (AttributeError, OSError, TypeError):
        return "unknown"


def _valid_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


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


def make_handler(ranker, api_token: str | None = None, rate_limit_per_minute: int | None = None):
    token = os.environ.get("REPOCORTEX_API_TOKEN", "") if api_token is None else api_token
    if rate_limit_per_minute is None:
        rate_limit_per_minute = int(os.environ.get(
            "REPOCORTEX_RATE_LIMIT_PER_MINUTE", str(DEFAULT_RATE_LIMIT_PER_MINUTE)))
    if rate_limit_per_minute < 1:
        raise ValueError("REPOCORTEX_RATE_LIMIT_PER_MINUTE must be at least 1")
    limiter = FixedWindowRateLimiter(rate_limit_per_minute)

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

        def _send(self, code: int, payload: dict, headers: dict[str, str] | None = None) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
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
            authenticated = False
            if token:
                supplied = self.headers.get("Authorization", "")
                expected = f"Bearer {token}"
                authenticated = hmac.compare_digest(
                    supplied.encode("utf-8", "surrogatepass"),
                    expected.encode("utf-8", "surrogatepass"),
                )
                if not authenticated:
                    self._send(401, {"error": "unauthorized"},
                               {"WWW-Authenticate": "Bearer"})
                    return
            client = _peer_ip(self)
            if authenticated:
                client = _valid_ip(self.headers.get(TRUSTED_CLIENT_IP_HEADER)) or client
            allowed, retry_after = limiter.allow(client)
            if not allowed:
                self._send(429, {"error": "too many requests"},
                           {"Retry-After": str(retry_after)})
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
            except (ValueError, RecursionError):
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
    ranker = load_ranker(runtime_directory(root))
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
