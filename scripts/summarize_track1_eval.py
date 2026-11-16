"""Validate registered arm outcomes and report paired cluster uncertainty.

The score file is intentionally simple: it contains the registration hash and,
for each repository, one record per registered case in each arm. A completed
record supplies numeric metrics. Any other status is retained and scored zero.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random

from scripts.register_track1_eval import ARMS, METRICS, canonical_json


def registration_digest(registration: dict) -> str:
    copy = dict(registration)
    claimed = copy.pop("registration_sha256", None)
    actual = hashlib.sha256(canonical_json(copy)).hexdigest()
    if claimed != actual:
        raise ValueError("registration digest mismatch")
    return actual


def validate_scores(registration: dict, scores: dict) -> dict:
    digest = registration_digest(registration)
    if scores.get("registration_sha256") != digest:
        raise ValueError("score file does not match the registration")
    registered = {item["repository"]: item for item in registration["repositories"]}
    submitted = {item["repository"]: item for item in scores.get("repositories", [])}
    if set(submitted) != set(registered):
        raise ValueError("score repositories do not exactly match the registration")

    normalized = {}
    for repository, spec in registered.items():
        case_specs = {case["case_id"]: case for case in spec["cases"]}
        arm_payload = submitted[repository].get("arms", {})
        if set(arm_payload) != set(ARMS):
            raise ValueError(f"{repository}: arms do not exactly match the protocol")
        normalized[repository] = {}
        for arm in ARMS:
            rows = arm_payload[arm]
            if len(rows) != len(case_specs):
                raise ValueError(f"{repository}/{arm}: one outcome is required per case")
            if len({row.get('case_id') for row in rows}) != len(rows):
                raise ValueError(f"{repository}/{arm}: duplicate case id")
            if {row.get("case_id") for row in rows} != set(case_specs):
                raise ValueError(f"{repository}/{arm}: case ids do not match registration")
            by_case = {}
            for row in rows:
                status = row.get("status")
                values = {}
                if status == "completed":
                    for metric in METRICS:
                        value = row.get(metric)
                        if not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
                            raise ValueError(f"{repository}/{arm}: invalid {metric}")
                        values[metric] = float(value)
                else:
                    if not isinstance(status, str) or not status:
                        raise ValueError(f"{repository}/{arm}: failures require a status")
                    values = {metric: 0.0 for metric in METRICS}
                by_case[row["case_id"]] = {"status": status, **values}
            normalized[repository][arm] = by_case
    return normalized


def paired_cluster_gap(cases: list[dict], learned: dict, baseline: dict,
                       metric: str, resamples: int, seed: int) -> dict:
    clusters = defaultdict(list)
    for case in cases:
        clusters[case["underlying_fix_id"]].append(
            learned[case["case_id"]][metric] - baseline[case["case_id"]][metric]
        )
    cluster_ids = sorted(clusters)
    cluster_means = {
        cluster: sum(values) / len(values) for cluster, values in clusters.items()
    }
    point = sum(cluster_means.values()) / len(cluster_means)
    rng = random.Random(seed)
    draws = []
    for _ in range(resamples):
        picked = [rng.choice(cluster_ids) for _ in cluster_ids]
        draws.append(sum(cluster_means[cluster] for cluster in picked) / len(picked))
    draws.sort()
    low_index = int(0.025 * (len(draws) - 1))
    high_index = int(0.975 * (len(draws) - 1))
    return {
        "cases": len(cases),
        "underlying_fixes": len(cluster_ids),
        "mean": round(point, 6),
        "lo": round(draws[low_index], 6),
        "hi": round(draws[high_index], 6),
    }


def summarize(registration: dict, scores: dict) -> dict:
    normalized = validate_scores(registration, scores)
    uncertainty = registration["uncertainty"]
    output = {
        "registration_sha256": registration["registration_sha256"],
        "protocol_version": registration["protocol_version"],
        "primary_metric": registration["primary_metric"],
        "failure_rule": registration["execution_contract"]["failure_after_scoring_starts"],
        "repositories": [],
    }
    for repository_spec in registration["repositories"]:
        repository = repository_spec["repository"]
        arms = normalized[repository]
        arm_summaries = {}
        for arm in ARMS:
            rows = arms[arm].values()
            arm_summaries[arm] = {
                "cases": len(arms[arm]),
                "completed": sum(row["status"] == "completed" for row in rows),
                "failures": dict(sorted(Counter(
                    row["status"] for row in arms[arm].values() if row["status"] != "completed"
                ).items())),
                **{
                    metric: round(sum(row[metric] for row in arms[arm].values()) / len(arms[arm]), 6)
                    for metric in METRICS
                },
            }
        gaps = {}
        for baseline in ("frozen_graph", "text_only"):
            gaps[f"learned_graph_minus_{baseline}"] = {
                metric: paired_cluster_gap(
                    repository_spec["cases"], arms["learned_graph"], arms[baseline], metric,
                    int(uncertainty["resamples"]), int(uncertainty["seed"]),
                )
                for metric in METRICS
            }
        output["repositories"].append({
            "repository": repository,
            "arms": arm_summaries,
            "paired_cluster_gaps": gaps,
        })
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--scores", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("--out already exists; choose a fresh evidence file")
    result = summarize(json.loads(args.registration.read_text()), json.loads(args.scores.read_text()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(canonical_json(result))
    print(json.dumps({"repositories": len(result["repositories"]), "out": str(args.out)}))


if __name__ == "__main__":
    main()
