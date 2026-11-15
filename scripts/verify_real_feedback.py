"""Check real Django feedback durability on local HydraDB, without retraining.

Example: python -m scripts.verify_real_feedback --ticket 37442 --diff fix.diff
Obtain the original diff from the exact dataset commit's GitHub .diff URL.
A held-out example deliberately becomes feedback here: this is NOT an accuracy
measurement. Only a temporary FeedbackRecord namespace is written and removed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from repocortex.config import Settings
from repocortex.hydradb import connect
from repocortex.hydradb.base import LABELS
from repocortex.serve.feedback import configure_feedback
from repocortex.serve.learn import functions_from_diff, learn_from_fix
from repocortex.serve.load import load_ranker, locate

RUNTIME_FILES = ["corpus.json", "embeddings.npz", "learned_state.json", "learned_state.npz", "dataset.json"]


def hashes(root):
    found = {}
    for name in RUNTIME_FILES:
        with (root / "data" / name).open("rb") as stream:
            found[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return found


def counts(client):
    return {"labels": {label: client.count_label(label) for label in LABELS}}


def worker(root, client, namespace, issue, diff):
    ranker = load_ranker(root)
    ranker.client = client
    mapped = functions_from_diff(diff, ranker.nodes)
    if set(mapped) != set(issue["gold_functions"]):
        raise ValueError("real diff mapping does not match the dataset's confirmed functions")
    setup = configure_feedback(ranker, namespace)
    report = issue["summary"] + "\n\n" + issue["description"]
    before = locate(ranker, report, k=10)
    memory_before = len(ranker.memory)
    outcome = learn_from_fix(ranker, report, diff)
    after = locate(ranker, report, k=10)
    duplicate = learn_from_fix(ranker, report, diff)
    return {"setup": setup, "mapped_functions": [
        {"uid": uid, **{key: ranker.nodes[uid][key] for key in ("file", "qualname", "start", "end")}} for uid in mapped],
        "before": before, "after": after, "memory_before": memory_before, "memory_after": len(ranker.memory),
        "feedback": {k: outcome[k] for k in ("ticket", "learned", "persistence", "skipped") if k in outcome},
        "duplicate_skipped": bool(duplicate.get("skipped"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", type=int, default=37442)
    parser.add_argument("--diff", required=True, type=Path)
    parser.add_argument("--phase", choices=["write", "reload"])
    parser.add_argument("--namespace")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    settings = Settings.load(root)
    if settings.backend != "bolt" or urlparse(settings.bolt_uri).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit("verification requires local Bolt; remote databases are refused")
    dataset = json.loads((root / "data/dataset.json").read_text())
    issue = next(row for row in dataset["issues"] if row["ticket"] == args.ticket)
    diff = args.diff.read_text()
    source = f"https://github.com/django/django/commit/{issue['commit']}.diff"
    if not args.phase:
        with urlopen(source, timeout=30) as response:
            original = response.read(2_000_000)
        if hashlib.sha256(original).hexdigest() != hashlib.sha256(args.diff.read_bytes()).hexdigest():
            raise ValueError("provided diff does not match the upstream dataset commit")
    client = connect(settings)
    try:
        if args.phase:
            if not args.namespace or not args.namespace.startswith("verify-real-"):
                raise SystemExit("worker requires an isolated verification namespace")
            print(json.dumps(worker(root, client, args.namespace, issue, diff)))
            return
        namespace = "verify-real-" + uuid.uuid4().hex
        runtime_before, graph_before = hashes(root), counts(client)
        phases = []
        try:
            for phase in ("write", "reload"):
                process = subprocess.run([sys.executable, "-m", "scripts.verify_real_feedback",
                    "--ticket", str(args.ticket), "--diff", str(args.diff.resolve()),
                    "--phase", phase, "--namespace", namespace], capture_output=True, text=True,
                    env={**os.environ, "HF_HUB_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false", "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2"})
                if process.returncode:
                    raise RuntimeError(f"{phase} verification failed; inspect the local worker without exposing connection details")
                phases.append(json.loads(process.stdout))
        finally:
            client.query("MATCH (n:FeedbackRecord) WHERE n.namespace = $namespace DETACH DELETE n", {"namespace": namespace})
        cleanup = client.query("MATCH (n:FeedbackRecord) WHERE n.namespace = $namespace RETURN count(*) AS n", {"namespace": namespace}).rows[0]["n"] == 0
        runtime_after, graph_after = hashes(root), counts(client)
        first, second = phases
        checks = {
            "diff_matches_upstream_commit": True,
            "actual_diff_maps_to_confirmed_function": set(first["feedback"]["learned"]) == set(issue["gold_functions"]),
            "one_feedback_event_learned": first["memory_after"] == first["memory_before"] + 1,
            "fresh_process_restores_exact_ranking": first["after"] == second["before"] == second["after"],
            "fresh_process_replays_one_event": second["setup"]["replayed"] == 1,
            "duplicates_skipped": first["duplicate_skipped"] and second["duplicate_skipped"] and bool(second["feedback"].get("skipped")),
            "runtime_files_unchanged": runtime_before == runtime_after,
            "benchmark_node_counts_unchanged_after_cleanup": graph_before == graph_after,
            "namespace_cleaned": cleanup,
        }
        print(json.dumps({"scope": "real Django report and confirmed diff; durability evidence, not held-out accuracy gain",
            "snapshot": dataset["snapshot"], "ticket": issue["ticket"], "dataset_split": issue["split"],
            "report_summary": issue["summary"], "commit": issue["commit"],
            "diff_source": f"https://github.com/django/django/commit/{issue['commit']}.diff",
            "diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
            "storage": "local HydraDB event journal; learned scoring state reconstructed in memory",
            "model": "existing MiniLM embeddings and locally cached model; no retraining",
            "runtime_sha256_before": runtime_before, "runtime_sha256_after": runtime_after,
            "graph_before": graph_before, "graph_after_cleanup": graph_after,
            "processes": phases, "checks": checks}, indent=2))
        if not all(checks.values()):
            raise SystemExit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()
