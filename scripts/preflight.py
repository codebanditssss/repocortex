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


def check_database(root: Path, functions: int, timeout: float = 15) -> bool:
    # A separate process bounds driver connection/retry time and suppresses
    # driver diagnostics, which may contain private connection details.
    probe = '''
import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from repocortex.config import Settings
from repocortex.hydradb import connect
client = connect(Settings.load(Path(sys.argv[1])))
try:
    status = client.ping()
    sys.exit(0 if status.get("repo") and status.get("functions") == int(sys.argv[2]) else 1)
finally:
    client.close()
'''
    try:
        result = subprocess.run([sys.executable, "-c", probe, str(root), str(functions)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=timeout, check=False)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", action="store_true", help="also check configured HydraDB with a 15-second deadline")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        print("FAIL: Python 3.11+ is required.")
        return 1
    missing = [name for name in MODULES if importlib.util.find_spec(name) is None]
    if missing:
        print("FAIL: missing Python packages: " + ", ".join(missing))
        print("Run: python -m pip install -e . (inside your virtual environment)")
    absent = [name for name in RUNTIME_FILES if not (ROOT / "data" / name).is_file()]
    if absent:
        print("FAIL: missing runtime files: " + ", ".join("data/" + name for name in absent))
        print("See docs/recovery.md. The graph export alone cannot replace these files.")
    if missing or absent:
        return 1
    try:
        count = check_runtime(ROOT)
    except Exception:
        print("FAIL: runtime artifacts are unreadable or inconsistent. Restore one matching snapshot; see docs/recovery.md.")
        return 1
    print(f"PASS: runtime artifacts are consistent ({count} indexed functions).")
    if args.database:
        if not check_database(ROOT, count):
            print("FAIL: HydraDB is unreachable, unconfigured, or has a different function count.")
            print("Check .env against .env.example and docs/recovery.md. No database writes were performed.")
            return 1
        print("PASS: configured HydraDB is reachable and its function count matches.")
    else:
        print("SKIP: database not checked; add --database before using live search or durable feedback.")
    print("The embedding model is not loaded by this check. First search may download MiniLM.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
