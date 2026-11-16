"""Freeze a leakage-safe prequential Track 1 study before scoring.

Registration reads frozen datasets and source checkouts, but never ranks a
query or applies a learning outcome.  It locks the chronological case groups,
raw inputs, source manifests, evaluator code, parameters, metrics and failure
rules that the runner must verify before it may score case one.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys

from scripts.register_track1_eval import (
    canonical_json,
    immutable_case_id,
    jaccard,
    normalized_query,
    query_shingles,
)


PROTOCOL_VERSION = "track1-prequential-v2"
ARMS = ("text_only", "frozen_graph", "flat_memory", "learned_graph")
METRICS = ("function_acc@10", "mrr")
FORBIDDEN_BASE_RELATIONS = ("CO_CHANGED", "FIXED_IN", "REFINES", "SAME_AS", "SHORTCUT")
DEFAULT_PARAMETERS = {
    "top_k": 10,
    "rolling_window": 10,
    "ranker": {
        "bm25_mix": 0.10,
        "memory_lam": 0.08,
        "memory_thresh": 0.55,
        "memory_k": 5,
        "shortcut_lam": 0.04,
        "shortcut_min_support": 3,
        "shortcut_min_precision": 0.4,
        "graph_mix": 0.05,
        "memory_agg": "sum",
        "memory_frontier": 0,
        "recency_half_life": 0.0,
        "file_prior_lam": 0.0,
        "module_prior_lam": 0.0,
        "prior_seeds": 12,
        "generalize_concepts": False,
        "credit_decay": 0.08,
    },
    "text_only_overrides": {
        "graph_mix": 0.0,
        "memory_lam": 0.0,
        "shortcut_lam": 0.0,
        "file_prior_lam": 0.0,
        "module_prior_lam": 0.0,
    },
    "learning": {"mode": "full", "lr": 0.25, "merger_every": 40, "decay": 0.08},
    "bootstrap": {"resamples": 10000, "seed": 20261116, "interval": 0.95},
}
NEAR_DUPLICATE_THRESHOLD = 0.35
RUNTIME_PACKAGES = (
    "huggingface-hub",
    "numpy",
    "scikit-learn",
    "scipy",
    "safetensors",
    "sentence-transformers",
    "tokenizers",
    "torch",
    "transformers",
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"path is outside the study repository: {path}") from exc


def file_manifest(root: Path, paths: list[Path]) -> tuple[list[dict], str]:
    records = []
    seen = set()
    for path in paths:
        relative = relative_to_root(path, root)
        if relative in seen:
            raise ValueError(f"duplicate evaluator source: {relative}")
        seen.add(relative)
        if not path.is_file():
            raise ValueError(f"evaluator source is not a file: {relative}")
        records.append({"path": relative, "sha256": sha256_bytes(path.read_bytes())})
    records.sort(key=lambda item: item["path"])
    return records, sha256_bytes(canonical_json(records))


def default_evaluator_paths(root: Path) -> list[Path]:
    tracked = git_output(root, "ls-files", "--", "repocortex").splitlines()
    paths = [root / path for path in sorted(path for path in tracked if path.endswith(".py"))]
    paths.extend(
        root / path
        for path in (
            "scripts/register_prequential_track1.py",
            "scripts/register_track1_eval.py",
            "scripts/run_prequential_track1.py",
        )
    )
    return paths


def runtime_identity() -> dict:
    executable = Path(sys.executable).resolve()
    packages = {}
    for name in RUNTIME_PACKAGES:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ValueError(f"required runtime package is missing: {name}") from exc
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "executable_name": executable.name,
        "executable_sha256": sha256_bytes(executable.read_bytes()),
        "packages": packages,
    }


def embedding_sentinel_sha256(snapshot: Path) -> str:
    import numpy as np
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(
        str(snapshot.resolve()), device="cpu", local_files_only=True, trust_remote_code=False
    )
    vector = model.encode(
        ["RepoCortex frozen embedding sentinel v1"],
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return sha256_bytes(np.asarray(vector, dtype="<f4").tobytes())


def model_artifact(snapshot: Path, sentinel_sha256: str) -> dict:
    snapshot = snapshot.resolve()
    if not snapshot.is_dir():
        raise ValueError(f"embedding model snapshot is not a directory: {snapshot}")
    records = []
    for path in sorted(item for item in snapshot.rglob("*") if item.is_file()):
        records.append(
            {
                "path": path.relative_to(snapshot).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    if not records:
        raise ValueError("embedding model snapshot contains no files")
    return {
        "model_name": "sentence-transformers/all-MiniLM-L6-v2",
        "revision": snapshot.name,
        "files": records,
        "manifest_sha256": sha256_bytes(canonical_json(records)),
        "sentinel": "RepoCortex frozen embedding sentinel v1",
        "sentinel_vector_sha256": sentinel_sha256,
        "loading": "local snapshot path only; network resolution is forbidden",
    }


def frozen_source_manifest(checkout: Path, scope: list[str]) -> tuple[list[dict], str]:
    """Hash only source text that the graph builder will consume at HEAD."""
    from repocortex.graph.builder import iter_sources

    records = []
    for name, source in iter_sources(checkout, tuple(scope)):
        stored = subprocess.run(
            ["git", "-C", str(checkout), "show", f"HEAD:{name}"],
            check=False,
            capture_output=True,
        )
        if stored.returncode or stored.stdout.decode("utf-8", errors="replace") != source:
            raise ValueError(f"indexed source differs from checkout HEAD: {name}")
        records.append({"path": name, "sha256": sha256_bytes(source.encode())})
    records.sort(key=lambda item: item["path"])
    if not records:
        raise ValueError(f"no source files found in registered scope: {scope}")
    return records, sha256_bytes(canonical_json(records))


def chronological_groups(dataset: dict) -> list[dict]:
    """Return training cases grouped so one fix cannot teach a sibling report."""
    repository = dataset["repository"]
    snapshot = dataset["snapshot"]
    rows = [row for row in dataset["issues"] if row.get("split") == "train"]
    if not rows:
        raise ValueError(f"{repository}: no training stream")
    rows.sort(key=lambda row: (int(row["time"]), str(row["commit"]), int(row["ticket"])))
    groups = []
    seen_tickets: set[int] = set()
    seen_case_ids: set[str] = set()
    commit_times: dict[str, int] = {}
    previous_key: tuple[int, str] | None = None
    for row in rows:
        ticket = int(row["ticket"])
        if ticket in seen_tickets:
            raise ValueError(f"{repository}: duplicate training ticket {ticket}")
        seen_tickets.add(ticket)
        commit = str(row["commit"])
        timestamp = int(row["time"])
        if commit in commit_times and commit_times[commit] != timestamp:
            raise ValueError(f"{repository}: one fix commit has multiple timestamps")
        commit_times[commit] = timestamp
        group_key = (timestamp, commit)
        if previous_key is not None and group_key < previous_key:
            raise ValueError(f"{repository}: non-chronological training stream")
        previous_key = group_key
        case_id = immutable_case_id(repository, snapshot, row)
        if case_id in seen_case_ids:
            raise ValueError(f"{repository}: duplicate immutable case id")
        seen_case_ids.add(case_id)
        case = {
            "case_id": case_id,
            "ticket": ticket,
            "time": int(row["time"]),
            "commit": row["commit"],
            "underlying_fix_id": f"{repository}@{row['commit']}",
            "query_sha256": sha256_bytes(
                " ".join(
                    f"{row.get('summary', '')} {row.get('description', '')}".lower().split()
                ).encode()
            ),
            "gold_sha256": sha256_bytes(
                canonical_json(
                    {
                        "functions": sorted(row["gold_functions"]),
                        "files": sorted(row["gold_files"]),
                    }
                )
            ),
        }
        if (
            groups
            and any(group["underlying_fix_id"] == case["underlying_fix_id"] for group in groups[:-1])
        ):
            raise ValueError(f"{repository}: one fix commit is split across the stream")
        if not groups or groups[-1]["underlying_fix_id"] != case["underlying_fix_id"]:
            groups.append(
                {
                    "group_index": len(groups) + 1,
                    "underlying_fix_id": case["underlying_fix_id"],
                    "time": case["time"],
                    "cases": [],
                }
            )
        groups[-1]["cases"].append(case)
    return groups


def holdout_cases(dataset: dict) -> list[dict]:
    repository = dataset["repository"]
    snapshot = dataset["snapshot"]
    rows = sorted(
        (row for row in dataset["issues"] if row.get("split") == "test"),
        key=lambda row: (int(row["time"]), str(row["commit"]), int(row["ticket"])),
    )
    if not rows:
        raise ValueError(f"{repository}: no fixed holdout cases")
    cases = []
    for row in rows:
        cases.append(
            {
                "case_id": immutable_case_id(repository, snapshot, row),
                "ticket": int(row["ticket"]),
                "time": int(row["time"]),
                "commit": row["commit"],
                "underlying_fix_id": f"{repository}@{row['commit']}",
                "query_sha256": sha256_bytes(
                    " ".join(
                        f"{row.get('summary', '')} {row.get('description', '')}".lower().split()
                    ).encode()
                ),
                "gold_sha256": sha256_bytes(
                    canonical_json(
                        {
                            "functions": sorted(row["gold_functions"]),
                            "files": sorted(row["gold_files"]),
                        }
                    )
                ),
            }
        )
    if len({case["case_id"] for case in cases}) != len(cases):
        raise ValueError(f"{repository}: duplicate fixed holdout case id")
    return cases


def checkpoint_groups(group_count: int, points: int = 5) -> list[int]:
    if group_count < 1:
        raise ValueError("at least one training fix group is required")
    steps = [int(round(index * group_count / (points - 1))) for index in range(points)]
    return list(dict.fromkeys(steps))


def audit_cross_split(dataset: dict, threshold: float = NEAR_DUPLICATE_THRESHOLD) -> dict:
    repository = dataset["repository"]
    train = [row for row in dataset["issues"] if row.get("split") == "train"]
    holdout = [row for row in dataset["issues"] if row.get("split") == "test"]
    checks = {
        "ticket": ({int(row["ticket"]) for row in train}, {int(row["ticket"]) for row in holdout}),
        "commit": ({str(row["commit"]) for row in train}, {str(row["commit"]) for row in holdout}),
        "exact_query": (
            {normalized_query(row) for row in train},
            {normalized_query(row) for row in holdout},
        ),
    }
    for name, (left, right) in checks.items():
        if left & right:
            raise ValueError(f"{repository}: cross-split {name} overlap")
    max_similarity = 0.0
    pairs_at_or_above = 0
    train_shingles = [query_shingles(row) for row in train]
    for row in holdout:
        held_out = query_shingles(row)
        for training in train_shingles:
            similarity = jaccard(training, held_out)
            max_similarity = max(max_similarity, similarity)
            if similarity >= threshold:
                pairs_at_or_above += 1
    if pairs_at_or_above:
        raise ValueError(
            f"{repository}: {pairs_at_or_above} cross-split near-duplicate query pairs"
        )
    return {
        "ticket_overlap": 0,
        "commit_overlap": 0,
        "exact_query_overlap": 0,
        "near_duplicate_method": "lowercase alphanumeric five-token shingle Jaccard",
        "near_duplicate_threshold": threshold,
        "pairs_at_or_above_threshold": 0,
        "maximum_similarity": round(max_similarity, 6),
    }


def build_registration(studies: list[tuple[Path, Path]], evaluator_paths: list[Path],
                       root: Path, model_snapshot: Path,
                       parameters: dict | None = None,
                       classification: str = "retrospective_reproducibility",
                       sentinel_sha256: str | None = None) -> dict:
    if classification not in {"prospective_confirmatory", "retrospective_reproducibility"}:
        raise ValueError("unknown study classification")
    evaluators, evaluator_digest = file_manifest(root, evaluator_paths)
    repositories = []
    names = set()
    for dataset_path, checkout in studies:
        raw = dataset_path.read_bytes()
        dataset = json.loads(raw)
        repository = dataset["repository"]
        if repository in names:
            raise ValueError(f"duplicate repository: {repository}")
        names.add(repository)
        if git_output(checkout, "rev-parse", "HEAD") != dataset["snapshot"]:
            raise ValueError(f"{repository}: checkout does not match dataset snapshot")
        source_records, source_digest = frozen_source_manifest(checkout, list(dataset["scope"]))
        split_audit = audit_cross_split(dataset)
        groups = chronological_groups(dataset)
        fixed_holdout = holdout_cases(dataset)
        repositories.append(
            {
                "repository": repository,
                "snapshot": dataset["snapshot"],
                "scope": list(dataset["scope"]),
                "dataset": {
                    "path": relative_to_root(dataset_path, root),
                    "sha256": sha256_bytes(raw),
                },
                "checkout": relative_to_root(checkout, root),
                "source_manifest": source_records,
                "source_manifest_sha256": source_digest,
                "stream_split": "train",
                "case_count": sum(len(group["cases"]) for group in groups),
                "fix_group_count": len(groups),
                "groups": groups,
                "holdout_cases": fixed_holdout,
                "holdout_case_count": len(fixed_holdout),
                "holdout_fix_count": len({case["underlying_fix_id"] for case in fixed_holdout}),
                "checkpoint_groups": checkpoint_groups(len(groups)),
                "cross_split_audit": split_audit,
            }
        )
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "git_head": git_output(root, "rev-parse", "HEAD"),
        "evaluator_sources": evaluators,
        "evaluator_source_manifest_sha256": evaluator_digest,
        "runtime": runtime_identity(),
        "embedding_model": model_artifact(
            model_snapshot,
            sentinel_sha256 or embedding_sentinel_sha256(model_snapshot),
        ),
        "arms": list(ARMS),
        "metrics": list(METRICS),
        "primary_metric": "function_acc@10",
        "study_classification": classification,
        "primary_estimand": (
            "at the final registered checkpoint only, paired learned_graph minus flat_memory "
            "function_acc@10 over fixed holdout cases, clustered by underlying fix commit"
        ),
        "secondary_estimands": [
            "prequential learned_graph minus flat_memory over chronological training reports",
            "prequential learned_graph minus frozen_graph over chronological training reports",
        ],
        "parameters": parameters or DEFAULT_PARAMETERS,
        "base_graph_contract": {
            "construction": "build_graph(iter_sources(checkout, registered scope))",
            "forbidden_relations_before_case_one": list(FORBIDDEN_BASE_RELATIONS),
            "isolation": "each arm receives a deep copy in a fresh EdgeTable",
        },
        "execution_contract": {
            "order": "ascending (fix time, commit, ticket) within the registered train split",
            "predict_then_learn": (
                "all reports sharing one fix commit are predicted in every arm before flat_memory "
                "and learned_graph atomically observe the same outcomes from that commit"
            ),
            "baselines": "text_only and frozen_graph never observe an outcome",
            "causal_control": (
                "flat_memory observes the same completed outcomes in the same fix groups as "
                "learned_graph but applies no graph learning operators"
            ),
            "failures": (
                "prediction failure remains in the case-weighted denominator as zero with no retry or "
                "replacement and its outcome is not exposed; an outcome-update failure atomically "
                "restores the last good learned state, retains the already-completed prediction, "
                "records the update failure, permanently disables later learning, and continues "
                "prediction from that last good state without rerun"
            ),
            "stopping": "score every registered group once; no outcome-dependent stopping",
        },
        "uncertainty": {
            "unit": "underlying fix commit",
            "method": "paired cluster bootstrap of learned minus baseline",
            **(parameters or DEFAULT_PARAMETERS)["bootstrap"],
        },
        "summary_weighting": "arm accuracy and MRR summaries are case-weighted",
        "holdout_curve": {
            "cases": "the registered test split, rescored unchanged at every registered checkpoint",
            "checkpoints": "five fixed positions from zero through all training fix groups",
            "primary_curve_statistic": (
                "descriptive only: end-minus-start change for each arm; the confirmatory test is "
                "the learned_graph minus flat_memory paired difference at the final checkpoint"
            ),
        },
        "decision_rule": (
            "For prospective_confirmatory: claim the registered primary success only if the "
            "final-checkpoint fixed-holdout function_acc@10 learned-minus-flat point estimate is "
            "positive, its registered two-sided 95% fix-cluster bootstrap lower bound is above zero, "
            "and the exact two-sided McNemar/binomial discordant-fix p-value is below .05. For "
            "retrospective_reproducibility: "
            "claim a consistent learning advantage only if the equal-repository aggregate is "
            "positive, at least three of four repository effects are positive, and the registered "
            "95% hierarchical bootstrap lower bound is above zero. Otherwise report no demonstrated "
            "advantage. Any prediction or outcome-update failure invalidates a confirmatory success "
            "claim. All metrics and failures are reported regardless."
        ),
        "cross_repository": {
            "aggregation": (
                "equal repository weight for final-checkpoint fixed-holdout learned-minus-flat effects"
            ),
            "hierarchical_bootstrap": (
                "resample repositories with replacement, then underlying holdout fix commits within "
                "each selected repository, preserving all reports from a sampled commit"
            ),
        },
        "curve": {
            "x": "number of reports predicted before learning their outcomes",
            "series": ["cumulative", "trailing rolling window"],
            "window": (parameters or DEFAULT_PARAMETERS)["rolling_window"],
        },
        "limitations": [
            "The final source snapshot can contain code from fixes later in the stream.",
            "Issue bodies can have been edited after their original fix.",
            "Mapped changed functions are a proxy for fault location.",
            "This offline in-memory evaluation does not prove hosted HydraDB behavior.",
            (
                "Datasets classified retrospective_reproducibility were mined and inspected before "
                "this protocol; prospective_confirmatory datasets were frozen under a prior selection plan."
            ),
        ],
        "repositories": repositories,
    }
    payload["registration_sha256"] = sha256_bytes(canonical_json(payload))
    return payload


def parse_study(value: str) -> tuple[Path, Path]:
    pieces = value.split("::")
    if len(pieces) != 2 or not all(pieces):
        raise argparse.ArgumentTypeError("study must be DATASET::CHECKOUT")
    return Path(pieces[0]), Path(pieces[1])


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", action="append", type=parse_study, required=True)
    parser.add_argument("--evaluator", action="append", type=Path)
    parser.add_argument("--model-snapshot", type=Path, required=True)
    parser.add_argument(
        "--classification",
        choices=("prospective_confirmatory", "retrospective_reproducibility"),
        required=True,
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("--out already exists; registrations are immutable")
    registration = build_registration(
        args.study,
        args.evaluator or default_evaluator_paths(root),
        root,
        args.model_snapshot,
        classification=args.classification,
        sentinel_sha256=embedding_sentinel_sha256(args.model_snapshot),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("xb") as output:
        output.write(canonical_json(registration))
    print(
        json.dumps(
            {
                "registration_sha256": registration["registration_sha256"],
                "repositories": len(registration["repositories"]),
                "cases": sum(item["case_count"] for item in registration["repositories"]),
            }
        )
    )


if __name__ == "__main__":
    main()
