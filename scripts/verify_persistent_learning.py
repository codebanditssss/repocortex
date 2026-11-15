"""Verify namespaced HydraDB feedback across fresh Python processes.

Uses two synthetic functions and fixed vectors: persistence/mechanism evidence,
not held-out accuracy. Never writes corpus nodes, benchmark edges or local state.
Requires a local Bolt instance configured through HYDRADB_BOLT_*; removes only
its own random FeedbackRecord namespace afterwards. No retraining.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

from repocortex.config import Settings
from repocortex.hydradb import connect
from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.dense import DenseIndex
from repocortex.retrieve.frozen import EdgeTable
from repocortex.retrieve.hybrid import HybridRanker
from repocortex.serve.feedback import configure_feedback
from repocortex.serve.learn import learn_from_fix
from repocortex.serve.load import locate
from scripts.demo_feedback import FixtureEmbedder

REPORT = "Synthetic regression reproduced"
DIFF = "--- a/fixture.py\n+++ b/fixture.py\n@@ -10,1 +10,1 @@\n-old\n+fixed\n"


def fixture_ranker(client=None):
    nodes = {
        f"func:fixture.py:{name}": {
            "label": "Function", "name": name, "qualname": name,
            "file": "fixture.py", "signature": "", "doc": "",
            "start": start, "end": start + 3,
        }
        for name, start in [("alpha", 1), ("beta", 10)]
    }
    return HybridRanker(nodes, EdgeTable({}), BM25Index.from_nodes(nodes),
                        DenseIndex(list(nodes), np.array([[1., 0.], [1., 0.]], dtype=np.float32)),
                        FixtureEmbedder(), client=client)


def worker(client, namespace, phase):
    ranker = fixture_ranker(client)
    loaded = configure_feedback(ranker, namespace)
    before = locate(ranker, REPORT, k=2)
    outcome = learn_from_fix(ranker, REPORT, DIFF)
    after = locate(ranker, REPORT, k=2)
    return {"phase": phase, "loaded": loaded, "before": before, "after": after,
            "feedback": {k: outcome[k] for k in ("ticket", "learned", "skipped", "persistence") if k in outcome},
            "memory_entries": len(ranker.memory),
            "learned_edges": len(ranker.edges.edges)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["write", "reload"])
    parser.add_argument("--namespace")
    args = parser.parse_args()
    settings = Settings.load(Path(__file__).resolve().parents[1])
    if settings.backend != "bolt" or urlparse(settings.bolt_uri).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("verification is restricted to a local Bolt instance")
    client = connect(settings)
    try:
        if args.phase:
            if not args.namespace or not args.namespace.startswith("verify-"):
                raise SystemExit("verification namespace must begin verify-")
            print(json.dumps(worker(client, args.namespace, args.phase)))
            return
        namespace = "verify-" + uuid.uuid4().hex
        counts = client.query("MATCH (n:Function) RETURN count(*) AS n").rows
        try:
            outputs = []
            for phase in ("write", "reload"):
                process = subprocess.run(
                    [sys.executable, "-m", "scripts.verify_persistent_learning", "--phase", phase, "--namespace", namespace],
                    capture_output=True, text=True, check=False,
                )
                if process.returncode:
                    raise RuntimeError(f"{phase} verification process failed")
                outputs.append(json.loads(process.stdout))
            first, second = outputs
            checks = {
                "confirmed_function_promoted": first["before"][0]["uid"] != first["after"][0]["uid"] and first["after"][0]["uid"] == "func:fixture.py:beta",
                "fresh_process_restores_ranking": first["after"] == second["before"],
                "duplicate_not_relearned": bool(second["feedback"].get("skipped")) and second["memory_entries"] == 1,
                "journal_replayed": second["loaded"]["replayed"] == 1,
                "benchmark_function_count_unchanged": counts == client.query("MATCH (n:Function) RETURN count(*) AS n").rows,
            }
            print(json.dumps({"scope": "synthetic persistence mechanism, not accuracy or generalization evidence",
                              "storage": "HydraDB journal; scoring edges reconstructed in memory",
                              "isolation": "random namespace, removed after verification; no corpus or benchmark edge writes",
                              "processes": outputs, "checks": checks}, indent=2))
            if not all(checks.values()):
                raise SystemExit(1)
        finally:
            client.query("MATCH (n:FeedbackRecord) WHERE n.namespace = $namespace DETACH DELETE n", {"namespace": namespace})
    finally:
        client.close()


if __name__ == "__main__":
    main()
