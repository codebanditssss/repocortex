"""Malformed HTTP JSON must fail without starting ranking work."""
import io
import json
import threading
import urllib.error
import urllib.request
from email.message import Message
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

from scripts import serve_locate


def _start(handler_type):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_type)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    return server, worker


def _post(server, headers=None):
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_port}/locate",
        data=json.dumps({"report": "bug"}).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, dict(response.headers), json.load(response)
    except urllib.error.HTTPError as response:
        with response:
            return response.code, dict(response.headers), json.load(response)


def test_oversized_json_integer_returns_client_error_without_ranking():
    # Python's integer digit limit raises ValueError, not JSONDecodeError.
    raw = b'{"report":"bug","unused":' + b'9' * 5000 + b'}'
    handler_type = serve_locate.make_handler(SimpleNamespace())
    handler = handler_type.__new__(handler_type)
    handler.path = "/locate"
    handler.headers = Message()
    handler.headers["Content-Length"] = str(len(raw))
    handler.rfile = io.BytesIO(raw)
    handler.connection = SimpleNamespace(settimeout=lambda _: None)
    replies = []
    handler._send = lambda code, payload: replies.append((code, payload))
    with patch.object(serve_locate, "locate_report") as rank:
        handler.do_POST()
        rank.assert_not_called()
    assert replies == [(400, {"error": "bad json"})]


def test_unicode_scalar_limit_is_independent_of_json_escaping():
    import json
    for escaped in (False, True):
        raw = json.dumps({"report": "😀" * 12000}, ensure_ascii=escaped).encode()
        assert len(raw) <= serve_locate.MAX_REQUEST_BYTES
        handler_type = serve_locate.make_handler(SimpleNamespace())
        handler = handler_type.__new__(handler_type)
        handler.path = "/locate"
        handler.headers = Message()
        handler.headers["Content-Length"] = str(len(raw))
        handler.rfile = io.BytesIO(raw)
        handler.connection = SimpleNamespace(settimeout=lambda _: None)
        replies = []
        handler._send = lambda code, payload: replies.append((code, payload))
        with patch.object(serve_locate, "locate_report", return_value={"hits": []}) as rank:
            handler.do_POST()
            assert rank.call_args.args[1] == "😀" * 12000
        assert replies == [(200, {"hits": []})]


def test_bearer_auth_rejects_missing_and_wrong_tokens_before_ranking():
    handler = serve_locate.make_handler(SimpleNamespace(), api_token="server-secret")
    server, worker = _start(handler)
    try:
        with patch.object(serve_locate, "backend_status", return_value={"mode": "live", "connected": True}), \
             patch.object(serve_locate, "locate_report") as rank:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_port}/health") as response:
                assert response.status == 200
            for headers in ({}, {"Authorization": "Bearer wrong"}):
                status, response_headers, payload = _post(server, headers)
                assert status == 401
                assert response_headers["WWW-Authenticate"] == "Bearer"
                assert payload == {"error": "unauthorized"}
            rank.assert_not_called()
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_rate_limit_ignores_spoofed_client_header_without_authentication():
    handler = serve_locate.make_handler(SimpleNamespace(), api_token="", rate_limit_per_minute=1)
    server, worker = _start(handler)
    try:
        with patch.object(serve_locate, "locate_report", return_value={"hits": []}) as rank:
            assert _post(server, {serve_locate.TRUSTED_CLIENT_IP_HEADER: "198.51.100.1"})[0] == 200
            status, headers, payload = _post(
                server, {serve_locate.TRUSTED_CLIENT_IP_HEADER: "203.0.113.2"})
            assert status == 429
            assert int(headers["Retry-After"]) >= 1
            assert payload == {"error": "too many requests"}
            assert rank.call_count == 1
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_authenticated_proxy_identity_gets_an_independent_bounded_window():
    handler = serve_locate.make_handler(
        SimpleNamespace(), api_token="server-secret", rate_limit_per_minute=1)
    server, worker = _start(handler)
    auth = {"Authorization": "Bearer server-secret"}
    try:
        with patch.object(serve_locate, "locate_report", return_value={"hits": []}) as rank:
            first = {**auth, serve_locate.TRUSTED_CLIENT_IP_HEADER: "198.51.100.1"}
            second = {**auth, serve_locate.TRUSTED_CLIENT_IP_HEADER: "203.0.113.2"}
            assert _post(server, first)[0] == 200
            assert _post(server, second)[0] == 200
            assert _post(server, first)[0] == 429
            assert rank.call_count == 2
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_rate_limiter_prunes_state_at_its_client_bound():
    limiter = serve_locate.FixedWindowRateLimiter(limit=1, window_seconds=60, max_clients=2)
    assert limiter.allow("first", now=0)[0]
    assert limiter.allow("second", now=1)[0]
    assert limiter.allow("third", now=2)[0]
    assert len(limiter._clients) == 2
    assert "first" not in limiter._clients
