"""Read-only setup checks; never load a model, train, or write to HydraDB."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = ("corpus.json", "embeddings.npz", "learned_state.json", "learned_state.npz")
MODULES = ("numpy", "neo4j", "httpx", "sentence_transformers", "mcp")


def check_runtime(root: Path) -> int:
    """Validate the artifact relationships used by load_ranker, without loading it."""
    import numpy as np

    corpus = json.loads((root / "data/corpus.json").read_text())
    nodes = corpus["nodes"]
    learned = json.loads((root / "data/learned_state.json").read_text())
    if not isinstance(nodes, dict) or not isinstance(learned, list):
        raise ValueError("unexpected corpus or learned-state structure")
    for row in learned:
        if not all(isinstance(row.get(key), str) and row[key] for key in ("src", "rel", "dst")):
            raise ValueError("invalid learned relationship")
    with np.load(root / "data/embeddings.npz", allow_pickle=False) as blob:
        uids, matrix = blob["uids"].tolist(), blob["matrix"]
        if (not uids or len(set(uids)) != len(uids) or matrix.ndim != 2
                or matrix.shape[0] != len(uids) or matrix.shape[1] != 384
                or not np.isfinite(matrix).all()):
            raise ValueError("invalid embedding rows or MiniLM dimensions")
        if any(nodes.get(uid, {}).get("label") != "Function" for uid in uids):
            raise ValueError("embedding IDs do not match corpus functions")
        width = matrix.shape[1]
    with np.load(root / "data/learned_state.npz", allow_pickle=False) as state:
        vectors, tickets, golds = state["vectors"], state["tickets"], state["golds"]
        if (vectors.shape != (len(tickets), width) or len(golds) != len(tickets)
                or not np.isfinite(vectors).all()):
            raise ValueError("fix memory dimensions do not match embeddings")
        known = set(uids)
        for encoded in golds.tolist():
            row = json.loads(encoded)
            if not isinstance(row, list) or any(uid not in known for uid in row):
                raise ValueError("fix memory references unknown functions")
    return len(uids)


def check_mcp(timeout: float = 10) -> bool:
    """Import the server's MCP entry point without starting it or loading settings."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", "from mcp.server.mcpserver import MCPServer"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=timeout, check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def runtime_remedy(runtime: Path) -> str:
    if runtime != ROOT.resolve():
        return ("For a custom index, rebuild the same repository into a NEW output directory "
                "with --embed --runtime; see docs/index-repository.md. "
                "Do not mix in Django runtime files. For a recovered runtime, restore its matching snapshot.")
    return "See docs/recovery.md. The graph export alone cannot replace these files."


def check_database(root: Path, functions: int, timeout: float = 15, repositories: set[str] | None = None) -> bool:
    # A separate process bounds driver connection/retry time and suppresses
    # driver diagnostics, which may contain private connection details.
    probe = '''
import sys, json
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from repocortex.config import Settings
from repocortex.hydradb import connect
settings = Settings.load(Path(sys.argv[1]))
if settings.backend != "bolt":
    sys.exit(1)
client = connect(settings)
try:
    status = client.ping()
    expected = json.loads(sys.argv[3])
    sys.exit(0 if status.get("repo") and status.get("functions") == int(sys.argv[2])
             and (not expected or status["repo"] in expected) else 1)
finally:
    client.close()
'''
    try:
        result = subprocess.run([sys.executable, "-c", probe, str(root), str(functions), json.dumps(sorted(repositories or []))],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=timeout, check=False)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", action="store_true", help="also check configured Bolt HydraDB with a 15-second deadline")
    parser.add_argument("--runtime", type=Path, help="root containing data/; defaults to REPOCORTEX_RUNTIME or this checkout")
    args = parser.parse_args()
    import os
    runtime = Path(args.runtime or os.environ.get("REPOCORTEX_RUNTIME") or ROOT).expanduser().resolve()
    if sys.version_info < (3, 11):
        print("FAIL: Python 3.11+ is required.")
        return 1
    missing = [name for name in MODULES if importlib.util.find_spec(name) is None]
    if missing:
        print("FAIL: missing Python packages: " + ", ".join(missing))
        print("Run: python -m pip install -e . (inside your virtual environment)")
    mcp_ok = "mcp" not in missing and check_mcp()
    if "mcp" not in missing and not mcp_ok:
        print("FAIL: MCP server dependencies cannot import in this Python environment (10-second deadline).")
        print("From this checkout, use the same virtual-environment Python to run: python -m pip install -e .")
        print("Then run python -m pip check and retry. No server or database connection was started.")
    absent = [name for name in RUNTIME_FILES if not (runtime / "data" / name).is_file()]
    if absent:
        print("FAIL: missing runtime files: " + ", ".join("data/" + name for name in absent))
        print(runtime_remedy(runtime))
    if missing or absent or not mcp_ok:
        return 1
    try:
        count = check_runtime(runtime)
    except Exception:
        print("FAIL: runtime artifacts are unreadable or inconsistent.")
        print(runtime_remedy(runtime))
        return 1
    print(f"PASS: runtime artifacts are consistent ({count} indexed functions).")
    if args.database:
        nodes = json.loads((runtime / "data/corpus.json").read_text())["nodes"]
        repositories = {uid for uid, node in nodes.items() if node.get("label") == "Repo"}
        if not check_database(ROOT, count, repositories=repositories):
            print("FAIL: HydraDB is unreachable, unconfigured, or its repository identity/function count differs.")
            print("Check .env against .env.example and docs/recovery.md. No database writes were performed.")
            return 1
        print("PASS: configured HydraDB is reachable and its repository identity/function count match.")
    else:
        print("SKIP: database not checked; add --database before using live search or durable feedback.")
    print("The embedding model is not loaded by this check. First search may download MiniLM.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
