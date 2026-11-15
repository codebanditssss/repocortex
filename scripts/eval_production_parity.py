"""Eight sequential, read-only HTTP searches compared with saved offline rankings.

Run: python -m scripts.eval_production_parity --url https://example/api/locate
No training, database mutations, retries, or outcome-based sample selection.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from repocortex.retrieve.textutil import issue_text
from repocortex.serve.load import load_ranker, locate
from scripts.eval_serving_parity import aggregate, compare, sample_indices


def select_rows(previous: dict) -> list[dict]:
    rows = previous["rows"]
    if len(rows) != 32:
        raise ValueError("requires the original 32-row local parity artifact")
    return [rows[index] for index in sample_indices(32, 8)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", type=Path, default=Path("results/production_parity.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    previous_path = root / "results/serving_parity.json"
    previous = json.loads(previous_path.read_text())
    chosen = select_rows(previous)  # fixed before any HTTP response
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    before = {name: digest(root / "data" / name) for name in previous["runtime_sha256"]}
    if before != previous["runtime_sha256"]:
        raise RuntimeError("runtime artifacts differ from the original local parity run")
    holdout = [i for i in json.loads((root / "data/dataset.json").read_text())["issues"] if i["split"] == "test"]
    ranker = load_ranker(root)
    prepared = []
    for row in chosen:
        issue = holdout[row["holdout_index"]]
        report = issue_text(issue).strip()
        offline = locate(ranker, report, 10)
        if [h["uid"] for h in offline] != row["offline_uids"]:
            raise RuntimeError("regenerated offline ranking differs from the fixed local artifact")
        prepared.append((row, report, offline))
    checked_at = datetime.now(timezone.utc).isoformat()
    responses = []
    for original, report, offline in prepared:
        request = Request(args.url, data=json.dumps({"report": report, "k": 10}).encode(), headers={"Content-Type": "application/json"})
        started = time.perf_counter()
        row = {"holdout_index": original["holdout_index"], "ticket": original["ticket"], "report_sha256": hashlib.sha256(report.encode()).hexdigest(), "offline_hits": offline}
        try:
            with urlopen(request, timeout=65) as response:
                payload = json.load(response)
                row.update(status=response.status, response=payload)
            row["valid_live_response"] = payload.get("source") == "live" and len(payload.get("hits", [])) == 10 and len(payload.get("queries", [])) > 0
            row["query_count"] = len(payload.get("queries", []))
            row["offline_to_production"] = compare(offline, payload.get("hits", []))
        except HTTPError as error:
            row.update(status=error.code, valid_live_response=False, error_type="HTTPError")
        except Exception as error:
            row.update(valid_live_response=False, error_type=type(error).__name__)
        row["seconds"] = time.perf_counter() - started
        responses.append(row)
        print(f"{len(responses)}/8 row {row['holdout_index']}: status {row.get('status')}, parity {row.get('offline_to_production')}", flush=True)
    after = {name: digest(root / "data" / name) for name in before}
    if after != before:
        raise RuntimeError("runtime files changed during audit")
    successful = [r for r in responses if r.get("valid_live_response")]
    result = {
        "checked_at": checked_at, "endpoint": args.url,
        "methodology": {"sample": 8, "population": len(holdout), "selection": "8 evenly spaced positions in the fixed 32-row local audit, selected before any production responses", "selected_holdout_indices": [r["holdout_index"] for r in chosen], "execution": "sequential HTTP POST searches, k=10, no retries, no training or graph writes", "limitations": "small parity sample, not full accuracy evaluation, capacity test, or proof all production queries match; latency includes network"},
        "reference_artifact_sha256": digest(previous_path), "runtime_sha256": before,
        "runtime_files_unchanged": True, "valid_live_responses": len(successful),
        "offline_to_production": aggregate(successful, "offline_to_production") if successful else None,
        "responses": responses,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("valid_live_responses", "offline_to_production")}, indent=2))
    return 0 if len(successful) == 8 and all(r["offline_to_production"]["exact_order"] for r in successful) else 1


if __name__ == "__main__":
    raise SystemExit(main())
