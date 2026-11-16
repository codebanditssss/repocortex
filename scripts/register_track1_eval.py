"""Freeze a leakage-audited Track 1 evaluation before any scoring.

This command reads already-mined repository datasets. It does not rank cases,
train a model, call a provider, or write a graph. The resulting registration
locks the cases, case order, arms, metrics, evaluator sources and failure rules.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess


PROTOCOL_VERSION = "track1-localization-v1"
ARMS = ("text_only", "frozen_graph", "learned_graph")
METRICS = ("function_acc@10", "mrr")


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def repository_relative(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"evaluator source is outside the repository: {path}") from exc
    return relative.as_posix()


def default_evaluator_paths(root: Path) -> list[Path]:
    tracked = git_output(root, "ls-files", "--", "repocortex").splitlines()
    relative = sorted(path for path in tracked if path.endswith(".py"))
    relative.append("scripts/eval_repository_ablation.py")
    return [root / path for path in relative]


def source_manifest(root: Path, evaluator_paths: list[Path]) -> tuple[list[dict], str, dict]:
    records = []
    seen = set()
    for path in evaluator_paths:
        relative = repository_relative(path, root)
        if relative in seen:
            raise ValueError(f"duplicate evaluator source: {relative}")
        seen.add(relative)
        if not path.exists():
            raise ValueError(f"evaluator source does not exist: {relative}")
        if not path.is_file():
            raise ValueError(f"evaluator source is not a file: {relative}")
        records.append({"path": relative, "sha256": sha256_bytes(path.read_bytes())})
    records.sort(key=lambda item: item["path"])
    manifest_digest = sha256_bytes(canonical_json(records))
    paths = [record["path"] for record in records]
    dirty = git_output(
        root, "status", "--porcelain", "--untracked-files=no", "--", *paths
    ).splitlines()
    git_state = {
        "head": git_output(root, "rev-parse", "HEAD"),
        "tracked_source_changes": sorted(line for line in dirty if line),
        "clean_required": False,
    }
    return records, manifest_digest, git_state


def normalized_query(row: dict) -> str:
    return " ".join(f"{row.get('summary', '')} {row.get('description', '')}".lower().split())


def query_shingles(row: dict, width: int = 5) -> set[str]:
    tokens = re.findall(r"[a-z0-9_]+", normalized_query(row))
    if not tokens:
        return set()
    if len(tokens) < width:
        return {" ".join(tokens)}
    return {" ".join(tokens[index:index + width]) for index in range(len(tokens) - width + 1)}


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def immutable_case_id(repository: str, snapshot: str, row: dict) -> str:
    identity = {
        "repository": repository,
        "snapshot": snapshot,
        "ticket": int(row["ticket"]),
        "commit": row["commit"],
        "time": int(row["time"]),
        "query_sha256": sha256_bytes(normalized_query(row).encode()),
        "gold_functions": sorted(row["gold_functions"]),
        "gold_files": sorted(row["gold_files"]),
        "split": row["split"],
    }
    return sha256_bytes(canonical_json(identity))


def audit_dataset(dataset: dict, near_duplicate_threshold: float) -> dict:
    repository = dataset["repository"]
    snapshot = dataset["snapshot"]
    rows = dataset["issues"]
    train = [row for row in rows if row["split"] == "train"]
    holdout = [row for row in rows if row["split"] == "test"]
    if not train or not holdout:
        raise ValueError(f"{repository}: both training and holdout rows are required")
    latest_train = max(int(row["time"]) for row in train)
    earliest_holdout = min(int(row["time"]) for row in holdout)
    if latest_train > earliest_holdout:
        raise ValueError(f"{repository}: split is not chronological")

    exact = {normalized_query(row) for row in train} & {normalized_query(row) for row in holdout}
    train_tickets = {int(row["ticket"]) for row in train}
    holdout_tickets = {int(row["ticket"]) for row in holdout}
    train_commits = {row["commit"] for row in train}
    holdout_commits = {row["commit"] for row in holdout}
    if exact or train_tickets & holdout_tickets or train_commits & holdout_commits:
        raise ValueError(f"{repository}: exact label or query overlap across the split")

    train_shingles = [(row, query_shingles(row)) for row in train]
    near_duplicates = []
    for held_out in holdout:
        held_out_shingles = query_shingles(held_out)
        for training, training_shingles in train_shingles:
            similarity = jaccard(training_shingles, held_out_shingles)
            if similarity >= near_duplicate_threshold:
                near_duplicates.append({
                    "training_ticket": int(training["ticket"]),
                    "holdout_ticket": int(held_out["ticket"]),
                    "five_token_shingle_jaccard": round(similarity, 6),
                })
    if near_duplicates:
        raise ValueError(
            f"{repository}: {len(near_duplicates)} near-duplicate train/holdout query pair(s) "
            f"at threshold {near_duplicate_threshold}"
        )

    cases = []
    seen_ids = set()
    for row in holdout:
        case_id = immutable_case_id(repository, snapshot, row)
        if case_id in seen_ids:
            raise ValueError(f"{repository}: duplicate immutable case id")
        seen_ids.add(case_id)
        cases.append({
            "case_id": case_id,
            "underlying_fix_id": f"{repository}@{row['commit']}",
            "ticket": int(row["ticket"]),
            "commit": row["commit"],
            "time": int(row["time"]),
            "query_sha256": sha256_bytes(normalized_query(row).encode()),
            "gold_sha256": sha256_bytes(canonical_json({
                "functions": sorted(row["gold_functions"]),
                "files": sorted(row["gold_files"]),
            })),
        })
    return {
        "repository": repository,
        "snapshot": snapshot,
        "scope": list(dataset["scope"]),
        "training_rows": len(train),
        "holdout_rows": len(holdout),
        "underlying_holdout_fixes": len({case["underlying_fix_id"] for case in cases}),
        "latest_training_fix_unix": latest_train,
        "earliest_holdout_fix_unix": earliest_holdout,
        "near_duplicate_check": {
            "method": "lowercase alphanumeric five-token shingle Jaccard",
            "threshold": near_duplicate_threshold,
            "pairs_at_or_above_threshold": 0,
        },
        "cases": cases,
    }


def build_registration(dataset_paths: list[Path], evaluator_paths: list[Path],
                       near_duplicate_threshold: float, root: Path) -> dict:
    datasets = []
    repositories = []
    seen_repositories = set()
    for path in dataset_paths:
        raw = path.read_bytes()
        dataset = json.loads(raw)
        repository = dataset["repository"]
        if repository in seen_repositories:
            raise ValueError(f"duplicate repository registration: {repository}")
        seen_repositories.add(repository)
        datasets.append({"path": str(path), "sha256": sha256_bytes(raw)})
        repositories.append(audit_dataset(dataset, near_duplicate_threshold))

    if not evaluator_paths:
        raise ValueError("at least one evaluator source must be frozen")
    evaluators, manifest_digest, git_state = source_manifest(root, evaluator_paths)

    return {
        "protocol_version": PROTOCOL_VERSION,
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "datasets": datasets,
        "evaluator_sources": evaluators,
        "source_manifest_sha256": manifest_digest,
        "git_source_state": git_state,
        "arms": list(ARMS),
        "primary_metric": "function_acc@10",
        "secondary_metrics": ["mrr"],
        "primary_estimand": "learned_graph minus frozen_graph",
        "uncertainty": {
            "method": "paired cluster bootstrap by underlying_fix_id",
            "resamples": 10000,
            "seed": 20261116,
            "interval": 0.95,
        },
        "execution_contract": {
            "case_order": "registration order for every arm",
            "pairing": "same immutable case_id in every arm",
            "parameters": "locked before scoring; no holdout tuning or case replacement",
            "abort_before_scoring": (
                "abort the repository if dataset, source, evaluator, snapshot, case-id, chronology, "
                "or overlap verification fails"
            ),
            "failure_after_scoring_starts": (
                "retain every registered case in the denominator; missing, timeout, provider, harness, "
                "or malformed outcomes score zero and remain visible by failure type"
            ),
            "stopping": "score every registered case once in every arm; no outcome-dependent stopping or retries",
        },
        "repositories": repositories,
    }


def with_registration_digest(registration: dict) -> dict:
    if "registration_sha256" in registration:
        raise ValueError("registration already has a digest")
    registration = dict(registration)
    registration["registration_sha256"] = sha256_bytes(canonical_json(registration))
    return registration


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, action="append", required=True)
    parser.add_argument("--evaluator", type=Path, action="append")
    parser.add_argument("--near-duplicate-threshold", type=float, default=0.35)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("--out already exists; registrations are immutable")
    if not 0 < args.near_duplicate_threshold <= 1:
        parser.error("--near-duplicate-threshold must be in (0, 1]")
    evaluators = args.evaluator or default_evaluator_paths(root)
    registration = build_registration(
        args.dataset, evaluators, args.near_duplicate_threshold, root
    )
    registration = with_registration_digest(registration)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(canonical_json(registration))
    print(json.dumps({
        "registration_sha256": registration["registration_sha256"],
        "repositories": len(registration["repositories"]),
        "holdout_cases": sum(len(item["cases"]) for item in registration["repositories"]),
    }))


if __name__ == "__main__":
    main()
