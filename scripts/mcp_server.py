"""RepoCortex MCP server.

stdio:

    python scripts/mcp_server.py

streamable HTTP (http://127.0.0.1:8765/mcp):

    python scripts/mcp_server.py --http
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from threading import Lock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.mcpserver import MCPServer

server = MCPServer(
    "repocortex",
    instructions=(
        "Locate the functions a bug report touches in the learned Django code graph, "
        "and fold a unified diff back into that graph."
    ),
)

_state = None
_state_lock = Lock()


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
    from repocortex.serve.load import load_ranker

    root = Path(__file__).resolve().parents[1]
    ranker = load_ranker(root)
    operators = make_operators(ranker, "full", lr=0.25, merger_every=40)
    for op in operators:
        if isinstance(op, PathCompressor):
            op.hydrate(ranker.edges)
    client = None
    try:
        from repocortex.hydradb import connect

        client = connect(Settings.load(root))
        ranker.client = client
    except Exception:
        client = None
    _state = {"ranker": ranker, "operators": operators, "root": root, "client": client}
    return _state


@server.tool(description="Rank functions for a bug report. Each hit includes file, line, score, and the provenance path. The payload also says whether HydraDB answered, and which bounded queries ran.")
def locate_bug(report: str, k: int = 10) -> dict:
    from repocortex.serve.load import locate_report

    k = max(1, min(int(k), 20))
    return locate_report(get_state()["ranker"], report, k)


@server.tool(description="Say whether the ranker is live on HydraDB, replaying the exported graph, or in error.")
def graph_status() -> dict:
    from repocortex.serve.load import backend_status

    return backend_status(get_state()["ranker"])


@server.tool(description="Predict, then learn from a unified diff of the fix. The prediction is made before the graph changes.")
def learn_from_fix(report: str, diff: str) -> dict:
    from repocortex.serve.learn import learn_from_fix as apply_fix

    state = get_state()
    with state["ranker"].request_lock:
        return apply_fix(
            state["ranker"],
            report,
            diff,
            operators=state["operators"],
            state_path=state["root"] / "data" / "learned_state.npz",
        )



def main() -> None:
    parser = argparse.ArgumentParser(description="RepoCortex MCP server")
    parser.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
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
