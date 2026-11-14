"""MCP stdio server. Exposes locate_bug(report) -> ranked functions and paths.

Run after scripts/run_eval.py --replay so data/learned_state.npz exists.
No LLM calls. GMI_API_KEY is unused.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repocortex.serve.load import load_ranker, locate


TOOL = {
    "name": "locate_bug",
    "description": "Rank functions a bug report is likely to touch, with the graph path behind each hit.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "report": {"type": "string", "description": "Bug report text."},
            "k": {"type": "integer", "description": "How many functions to return.", "default": 10},
        },
        "required": ["report"],
        "additionalProperties": False,
    },
}


def handle(message: dict, locate_fn) -> dict | None:
    method = message.get("method")
    msg_id = message.get("id")
    if msg_id is None:
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "repocortex", "version": "0.2"},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": [TOOL]}}
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        if name != "locate_bug":
            return _error(msg_id, f"unknown tool {name}")
        args = params.get("arguments") or {}
        report = str(args.get("report") or "")
        try:
            k = int(args.get("k") or 10)
        except (TypeError, ValueError):
            k = 10
        hits = locate_fn(report, k)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps({"hits": hits})}],
                "isError": False,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    return _error(msg_id, f"unknown method {method}")


def _error(msg_id, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": message}}


def read_message(stream) -> dict | None:
    headers = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        decoded = line.decode("utf-8", errors="replace")
        if ":" not in decoded:
            continue
        key, value = decoded.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length") or 0)
    if length <= 0:
        return None
    return json.loads(stream.read(length).decode("utf-8"))


def write_message(stream, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    stream.write(body)
    stream.flush()


def serve(locate_fn, stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    while True:
        message = read_message(stdin)
        if message is None:
            return
        response = handle(message, locate_fn)
        if response is not None:
            write_message(stdout, response)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    ranker = load_ranker(root)

    def locate_fn(report: str, k: int = 10):
        return locate(ranker, report, k)

    serve(locate_fn)


if __name__ == "__main__":
    main()
