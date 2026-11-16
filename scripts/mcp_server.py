"""RepoCortex MCP server.

stdio:

    python scripts/mcp_server.py

streamable HTTP (http://127.0.0.1:8765/mcp):

    python scripts/mcp_server.py --http
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from threading import Lock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.mcpserver import MCPServer

server = MCPServer(
    "repocortex",
    instructions=(
        "Locate the functions a bug report touches in the configured repository code graph, "
        "and fold a unified diff back into that graph."
    ),
)

_state = None
_state_lock = Lock()
_http_mode = False
MAX_DIFF_BYTES = 256_000

def _validate_report(report: str) -> str:
    if not isinstance(report, str) or not report.strip() or len(report) > 12000:
        raise ValueError("report must contain 1 to 12000 characters")
    return report.strip()



def get_state():
    with _state_lock:
        return _load_state()


def _load_state():
    global _state
    if _state is not None:
        return _state
    from repocortex.config import Settings
    from repocortex.learn.compress import PathCompressor
    from repocortex.learn.replay import make_operators
    from repocortex.serve.load import load_ranker, runtime_directory

    root = Path(__file__).resolve().parents[1]
    ranker = load_ranker(runtime_directory(root))
    operators = make_operators(ranker, "full", lr=0.25, merger_every=40)
    for op in operators:
        if isinstance(op, PathCompressor):
            op.hydrate(ranker.edges)
    namespace = os.environ.get("REPOCORTEX_FEEDBACK_NAMESPACE", "").strip()
    settings = Settings.load(root)
    if namespace and settings.backend != "bolt":
        raise ValueError("durable feedback requires the Bolt backend")
    client = None
    try:
        from repocortex.hydradb import connect

        client = connect(settings)
        ranker.client = client
    except Exception:
        client = None
    if namespace:
        from repocortex.serve.feedback import configure_feedback
        try:
            _require_feedback_backend(ranker)
            configure_feedback(ranker, namespace, operators=operators)
        except Exception:
            if client is not None:
                client.close()
            raise
    _state = {"ranker": ranker, "operators": operators, "root": root, "client": client}
    return _state


def _require_feedback_backend(ranker):
    from repocortex.serve.load import backend_status
    status = backend_status(ranker)
    if status.get("mode") != "live" or not status.get("connected"):
        raise RuntimeError("feedback requires a healthy HydraDB matching this runtime; no feedback was written")


@server.tool(description="Rank functions for a bug report. Each hit includes file, line, score, and the provenance path. The payload also says whether HydraDB answered, and which bounded queries ran.")
def locate_bug(report: str, k: int = 10) -> dict:
    from repocortex.serve.load import locate_report

    report = _validate_report(report)
    if type(k) is not int or not 1 <= k <= 20:
        raise ValueError("k must be an integer from 1 to 20")
    return locate_report(get_state()["ranker"], report, k)


@server.tool(description="Say whether the ranker is live on HydraDB, replaying the exported graph, or in error.")
def graph_status() -> dict:
    from repocortex.serve.load import backend_status

    return backend_status(get_state()["ranker"])


@server.tool(description="Predict, then learn from a unified diff of the fix in a configured durable feedback namespace. The prediction is made before the graph changes.")
def learn_from_fix(report: str, diff: str) -> dict:
    from repocortex.serve.learn import learn_from_fix as apply_fix

    if _http_mode:
        raise ValueError("feedback is available only through the trusted local stdio server")
    report = _validate_report(report)
    if not isinstance(diff, str) or not diff.strip() or len(diff.encode("utf-8")) > MAX_DIFF_BYTES:
        raise ValueError("diff must contain 1 to 256000 UTF-8 bytes")
    from repocortex.serve.load import RankingBusyError, REQUEST_LOCK_TIMEOUT_SECONDS
    state = get_state()
    if getattr(state["ranker"], "feedback_journal", None) is None:
        raise ValueError(
            "feedback requires a durable namespace; set REPOCORTEX_FEEDBACK_NAMESPACE "
            "and restart the local stdio server before calling learn_from_fix"
        )
    if not state["ranker"].request_lock.acquire(timeout=REQUEST_LOCK_TIMEOUT_SECONDS):
        raise RankingBusyError("ranking is busy; try again shortly")
    try:
        _require_feedback_backend(state["ranker"])
        return apply_fix(
            state["ranker"],
            report,
            diff,
            operators=state["operators"],
        )
    finally:
        state["ranker"].request_lock.release()



def main() -> None:
    global _http_mode
    parser = argparse.ArgumentParser(description="RepoCortex MCP server")
    parser.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    _http_mode = args.http
    if args.http:
        server.run(
            "streamable-http",
            host=args.host,
            port=args.port,
            streamable_http_path="/mcp",
            stateless_http=True,
        )
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
