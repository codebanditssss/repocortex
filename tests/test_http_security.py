"""Malformed HTTP JSON must fail without starting ranking work."""
import io
from email.message import Message
from types import SimpleNamespace
from unittest.mock import patch

from scripts import serve_locate


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
