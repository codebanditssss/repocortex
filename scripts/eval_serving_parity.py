"""Read-only comparison of offline evaluation and live serving on saved holdout rows.

Uses the configured HydraDB, never trains or writes graph/runtime state. This is
ranking parity, not a new accuracy benchmark or a production load test.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from repocortex.config import Settings
from repocortex.hydradb import connect
from repocortex.retrieve.textutil import issue_text
from repocortex.serve.load import load_ranker, locate, locate_report


def sample_indices(total: int, count: int) -> list[int]:
    if total < 1 or count < 1:
        raise ValueError("sample and population must be positive")
    count = min(total, count)
    if count == 1:
        return [0]
    return [i * (total - 1) // (count - 1) for i in range(count)]


def compare(left: list[dict], right: list[dict]) -> dict:
    a, b = [h["uid"] for h in left], [h["uid"] for h in right]
    common = set(a) & set(b)
    scores_a = {h["uid"]: h["score"] for h in left}
    scores_b = {h["uid"]: h["score"] for h in right}
    return {
        "exact_order": a == b,
        "top1_match": bool(a and b and a[0] == b[0]),
        "overlap": len(common) / max(len(a), len(b), 1),
        "max_common_score_delta": max((abs(scores_a[u] - scores_b[u]) for u in common), default=0),
    }


def aggregate(rows: list[dict], key: str) -> dict:
    pairs = [row[key] for row in rows]
    return {
        "n": len(pairs),
        "exact_order_count": sum(p["exact_order"] for p in pairs),
        "top1_match_count": sum(p["top1_match"] for p in pairs),
        "mean_top10_overlap": sum(p["overlap"] for p in pairs) / len(pairs),
        "max_common_score_delta": max(p["max_common_score_delta"] for p in pairs),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=32)
    parser.add_argument("--output", type=Path, default=Path("results/serving_parity.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    files = [root / "data" / name for name in ("corpus.json", "dataset.json", "embeddings.npz", "learned_state.json", "learned_state.npz")]
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    before = {p.name: digest(p) for p in files}
    source_files = [root / "repocortex" / part for part in ("serve/load.py", "retrieve/hybrid.py", "hydradb/bolt.py", "retrieve/textutil.py")]
    source_before = {str(p.relative_to(root)): digest(p) for p in source_files}
    dataset = json.loads(files[1].read_text())
    holdout = [i for i in dataset["issues"] if i["split"] == "test"]
    ranker = load_ranker(root)
    client = connect(Settings.load(root))
    rows = []
    try:
        for index in sample_indices(len(holdout), args.sample):
            issue = holdout[index]
            # No ticket cache reuse: a row's text must determine its query vector.
            ranker._vec.clear()
            ranker.client = None
            started = time.perf_counter()
            benchmark = ranker.predict(issue, k=10)
            benchmark_hits = [{"uid": h.uid, "score": round(float(h.score), 4)} for h in benchmark.hits]
            benchmark_seconds = time.perf_counter() - started
            report = issue_text(issue).strip()  # same normalization as HTTP handler
            started = time.perf_counter()
            offline = locate(ranker, report)
            offline_seconds = time.perf_counter() - started
            ranker.client = client
            started = time.perf_counter()
            live = locate_report(ranker, report)
            live_seconds = time.perf_counter() - started
            if live["source"] != "live" or not live["queries"]:
                raise RuntimeError("comparison requires live database query receipts")
            row = {
                "holdout_index": index, "ticket": issue["ticket"],
                "benchmark_to_serving": compare(benchmark_hits, offline),
                "offline_to_live": compare(offline, live["hits"]),
                "seconds": {"benchmark": benchmark_seconds, "offline_serving": offline_seconds, "live_serving": live_seconds},
                "query_count": len(live["queries"]),
                "benchmark_uids": [h["uid"] for h in benchmark_hits],
                "offline_uids": [h["uid"] for h in offline],
                "live_uids": [h["uid"] for h in live["hits"]],
            }
            rows.append(row)
            print(f"{len(rows)}/{min(args.sample, len(holdout))}: row {index}, live {live_seconds:.2f}s, parity {row['offline_to_live']['exact_order']}", flush=True)
    finally:
        client.close()
    after = {p.name: digest(p) for p in files}
    if after != before:
        raise RuntimeError("runtime files changed during parity audit")
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "methodology": {
            "population": len(holdout), "sample": len(rows),
            "selection": ("all chronological holdout rows; no exclusions" if len(rows) == len(holdout) else "evenly spaced chronological holdout row indices, including first and last; no outcome-based selection"),
            "execution": "sequential local restored HydraDB reads, same ranker and learned memory, no training or graph writes",
            "scope": "direct serving functions, not HTTP transport; this does not certify production database parity",
            "cache": "benchmark ticket-vector cache cleared for each sampled row; serving uses ticket 0",
            "timing": "one pass, not a load test; shared process caches can favor later calls",
            "input": "benchmark uses summary plus description; serving receives their 4000-character text stripped, as the HTTP handler does",
        },
        "runtime_sha256": before, "runtime_files_unchanged": True,
        "source_sha256_at_start": source_before,
        "source_sha256_at_completion": {str(p.relative_to(root)): digest(p) for p in source_files},
        "source_files_unchanged": all(digest(p) == source_before[str(p.relative_to(root))] for p in source_files),
        "source_hash_scope": "on-disk files observed at audit start and completion; not a hash of imported Python objects",
        "live_timing_seconds": {"min": min(r["seconds"]["live_serving"] for r in rows), "mean": sum(r["seconds"]["live_serving"] for r in rows) / len(rows), "max": max(r["seconds"]["live_serving"] for r in rows)},
        "benchmark_to_serving": aggregate(rows, "benchmark_to_serving"),
        "offline_to_live": aggregate(rows, "offline_to_live"),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("benchmark_to_serving", "offline_to_live")}, indent=2))


if __name__ == "__main__":
    main()
