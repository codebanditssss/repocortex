"""Run one repository from a frozen prequential Track 1 registration.

The runner refuses to score until registration, dataset, checkout, indexed
source and evaluator hashes all match.  It constructs the base graph only from
the registered source snapshot and predicts an entire fix-commit group before
letting the learned arm observe any outcome in that group.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import random
import sys

from repocortex.eval.metrics import score_issue
from repocortex.graph.builder import build_graph, iter_sources
from repocortex.learn.base import Episode
from repocortex.learn.credit import credit_and_debit
from repocortex.learn.replay import make_operators
from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.dense import Embedder, build_dense_index
from repocortex.retrieve.frozen import EdgeTable
from repocortex.retrieve.hybrid import HybridRanker, QueryCache
from scripts.register_prequential_track1 import (
    ARMS,
    METRICS,
    canonical_json,
    chronological_groups,
    frozen_source_manifest,
    embedding_sentinel_sha256,
    holdout_cases,
    model_artifact,
    runtime_identity,
    sha256_bytes,
)


def validate_registration(registration: dict, root: Path, model_snapshot: Path) -> str:
    claimed = registration.get("registration_sha256")
    payload = dict(registration)
    payload.pop("registration_sha256", None)
    actual = sha256_bytes(canonical_json(payload))
    if claimed != actual:
        raise ValueError("registration digest mismatch")
    for source in registration["evaluator_sources"]:
        path = root / source["path"]
        if not path.is_file() or sha256_bytes(path.read_bytes()) != source["sha256"]:
            raise ValueError(f"evaluator source mismatch: {source['path']}")
    manifest = registration["evaluator_sources"]
    if sha256_bytes(canonical_json(manifest)) != registration["evaluator_source_manifest_sha256"]:
        raise ValueError("evaluator source manifest mismatch")
    if runtime_identity() != registration["runtime"]:
        raise ValueError("Python or package runtime mismatch")
    registered_model = registration["embedding_model"]
    current_model = model_artifact(
        model_snapshot, embedding_sentinel_sha256(model_snapshot)
    )
    if current_model != registered_model:
        raise ValueError("embedding model artifact mismatch")
    return actual


class LocalEmbedder:
    def __init__(self, snapshot: Path, model_name: str):
        import numpy as np
        from sentence_transformers import SentenceTransformer

        self._np = np
        self.model_name = model_name
        self.model = SentenceTransformer(
            str(snapshot.resolve()),
            device="cpu",
            local_files_only=True,
            trust_remote_code=False,
        )

    def encode(self, texts: list[str]):
        vectors = self.model.encode(
            texts,
            batch_size=64,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return self._np.asarray(vectors, dtype=self._np.float32)

    def encode_one(self, text: str):
        return self.encode([text])[0]


def verify_repository(spec: dict, root: Path) -> tuple[dict, Path]:
    dataset_path = root / spec["dataset"]["path"]
    raw = dataset_path.read_bytes()
    if sha256_bytes(raw) != spec["dataset"]["sha256"]:
        raise ValueError("dataset digest mismatch")
    dataset = json.loads(raw)
    checkout = root / spec["checkout"]
    from scripts.register_prequential_track1 import git_output

    if git_output(checkout, "rev-parse", "HEAD") != spec["snapshot"]:
        raise ValueError("checkout snapshot mismatch")
    sources, digest = frozen_source_manifest(checkout, spec["scope"])
    if sources != spec["source_manifest"] or digest != spec["source_manifest_sha256"]:
        raise ValueError("indexed source manifest mismatch")
    if chronological_groups(dataset) != spec["groups"]:
        raise ValueError("registered stream no longer matches dataset")
    if holdout_cases(dataset) != spec["holdout_cases"]:
        raise ValueError("registered fixed holdout no longer matches dataset")
    return dataset, checkout


def assert_clean_base_graph(graph, forbidden: set[str]) -> None:
    present = sorted({key[1] for key in graph.edges} & forbidden)
    if present:
        raise ValueError(f"base graph contains outcome-derived relations: {present}")


def fresh_ranker(nodes: dict, edges: dict, bm25, dense, embedder, params: dict,
                 cache: QueryCache, vectors: dict) -> HybridRanker:
    ranker = HybridRanker(
        {uid: dict(node) for uid, node in nodes.items()},
        EdgeTable({key: dict(value) for key, value in edges.items()}),
        bm25,
        dense,
        embedder,
        client=None,
        **params,
    )
    ranker.score_cache = cache
    ranker._vec = vectors
    return ranker


def query_only(issue: dict) -> dict:
    return {
        "ticket": int(issue["ticket"]),
        "summary": issue.get("summary", ""),
        "description": issue.get("description", ""),
    }


def apply_outcome(ranker, issue: dict, prediction, operators: list) -> Counter:
    """Apply one outcome after every sibling report in its fix group was predicted."""
    credit, debit, promoted = credit_and_debit(prediction, issue["gold_functions"])
    episode = Episode(
        ticket=int(issue["ticket"]),
        seeds=list(prediction.seeds),
        gold=list(issue["gold_functions"]),
        predicted=[hit.uid for hit in prediction.hits],
        traversed=list(prediction.traversed),
        credit=credit,
        debit=debit,
        concepts=list(prediction.concepts),
        promoted=promoted,
        frontier=list(prediction.frontier),
        gap_concepts=list(getattr(prediction, "gap_concepts", []) or []),
    )
    extra = ranker.gold_concepts(issue["gold_functions"])
    for concept in extra:
        if concept not in episode.concepts:
            episode.concepts.append(concept)
    applied = Counter()
    for operator in operators:
        result = operator.on_outcome(ranker.edges, episode)
        applied[result.name] += int(result.applied)
    ranker.observe(issue)
    return applied


def snapshot_learning_state(ranker, operators: list) -> dict:
    ranker_fields = (
        "edges",
        "nodes",
        "pending_nodes",
        "concepts",
        "symptoms",
        "memory",
        "fix_count",
        "_seen",
        "_mem_mat",
        "_mem_dirty",
    )
    operator_states = []
    for operator in operators:
        operator_states.append(
            {
                key: copy.deepcopy(value)
                for key, value in operator.__dict__.items()
                if key not in {"ranker", "nodes"}
            }
        )
    return {
        "ranker": {name: copy.deepcopy(getattr(ranker, name)) for name in ranker_fields},
        "operators": operator_states,
    }


def restore_learning_state(ranker, operators: list, snapshot: dict) -> None:
    for name, value in snapshot["ranker"].items():
        setattr(ranker, name, value)
    for operator, state in zip(operators, snapshot["operators"]):
        references = {
            key: value for key, value in operator.__dict__.items() if key in {"ranker", "nodes"}
        }
        operator.__dict__.clear()
        operator.__dict__.update(copy.deepcopy(state))
        operator.__dict__.update(references)
        if "ranker" in operator.__dict__:
            operator.ranker = ranker
        if "nodes" in operator.__dict__:
            operator.nodes = ranker.nodes


def apply_outcome_atomic(ranker, issue: dict, prediction, operators: list) -> Counter:
    snapshot = snapshot_learning_state(ranker, operators)
    try:
        return apply_outcome(ranker, issue, prediction, operators)
    except Exception:
        restore_learning_state(ranker, operators, snapshot)
        raise


def attempt_learning_update(ranker, issue: dict, prediction, operators: list,
                            enabled: bool) -> tuple[bool, str, Counter, str | None]:
    if not enabled:
        return False, "disabled_after_update_failure", Counter(), None
    try:
        applied = apply_outcome_atomic(ranker, issue, prediction, operators)
        return True, "applied", applied, None
    except Exception as exc:
        return False, "failed_atomic_rollback", Counter(), type(exc).__name__


def attempt_paired_update(flat_ranker, learned_ranker, issue: dict, prediction,
                          operators: list, enabled: bool) -> tuple[bool, str, Counter, str | None]:
    if not enabled:
        return False, "disabled_after_update_failure", Counter(), None
    flat_snapshot = snapshot_learning_state(flat_ranker, [])
    learned_snapshot = snapshot_learning_state(learned_ranker, operators)
    try:
        flat_ranker.observe(issue)
        applied = apply_outcome(learned_ranker, issue, prediction, operators)
        return True, "applied", applied, None
    except Exception as exc:
        restore_learning_state(flat_ranker, [], flat_snapshot)
        restore_learning_state(learned_ranker, operators, learned_snapshot)
        return False, "failed_atomic_rollback", Counter(), type(exc).__name__


def curve_points(rows: list[dict], window: int) -> list[dict]:
    totals = {metric: 0.0 for metric in METRICS}
    output = []
    for index, row in enumerate(rows, start=1):
        point = {"index": index, "case_id": row["case_id"], "ticket": row["ticket"]}
        start = max(0, index - window)
        for metric in METRICS:
            totals[metric] += float(row[metric])
            point[f"cumulative_{metric}"] = round(totals[metric] / index, 6)
            point[f"rolling_{metric}"] = round(
                sum(float(item[metric]) for item in rows[start:index]) / (index - start), 6
            )
        output.append(point)
    return output


def paired_cluster_gap(cases: list[dict], learned: dict, baseline: dict, metric: str,
                       resamples: int, seed: int, interval: float) -> dict:
    clusters = defaultdict(list)
    for case in cases:
        case_id = case["case_id"]
        clusters[case["underlying_fix_id"]].append(
            float(learned[case_id][metric]) - float(baseline[case_id][metric])
        )
    ids = sorted(clusters)
    means = {key: sum(clusters[key]) / len(clusters[key]) for key in ids}
    point = sum(means.values()) / len(means)
    rng = random.Random(seed)
    draws = sorted(
        sum(means[rng.choice(ids)] for _ in ids) / len(ids) for _ in range(resamples)
    )
    tail = (1.0 - interval) / 2.0
    return {
        "cases": len(cases),
        "underlying_fixes": len(ids),
        "mean": round(point, 6),
        "interval": interval,
        "weighting": "equal weight per underlying fix commit; reports within a commit are averaged",
        "lo": round(draws[int(tail * (len(draws) - 1))], 6),
        "hi": round(draws[int((1.0 - tail) * (len(draws) - 1))], 6),
    }


def score_cases(ranker, cases: list[dict], rows_by_ticket: dict, top_k: int) -> list[dict]:
    rows = []
    for case in cases:
        issue = rows_by_ticket[case["ticket"]]
        try:
            prediction = ranker.predict(issue, k=top_k)
            metrics = score_issue(
                [hit.uid for hit in prediction.hits],
                [hit.file for hit in prediction.hits],
                issue["gold_functions"],
                issue["gold_files"],
            )
            rows.append(
                {
                    "case_id": case["case_id"],
                    "ticket": case["ticket"],
                    "underlying_fix_id": case["underlying_fix_id"],
                    "status": "completed",
                    **{metric: metrics[metric] for metric in METRICS},
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "case_id": case["case_id"],
                    "ticket": case["ticket"],
                    "underlying_fix_id": case["underlying_fix_id"],
                    "status": "harness_error",
                    "error_type": type(exc).__name__,
                    **{metric: 0.0 for metric in METRICS},
                }
            )
    return rows


def summarize_case_rows(rows: list[dict]) -> dict:
    return {
        "cases": len(rows),
        "completed": sum(row["status"] == "completed" for row in rows),
        "failures": dict(sorted(Counter(
            row["status"] for row in rows if row["status"] != "completed"
        ).items())),
        **{
            metric: round(sum(float(row[metric]) for row in rows) / len(rows), 6)
            for metric in METRICS
        },
    }


def holdout_delta_of_deltas(checkpoints: dict, cases: list[dict], metric: str,
                            resamples: int, seed: int, interval: float) -> dict:
    learned_start = {row["case_id"]: row for row in checkpoints["learned_graph"][0]["cases"]}
    learned_end = {row["case_id"]: row for row in checkpoints["learned_graph"][-1]["cases"]}
    flat_start = {row["case_id"]: row for row in checkpoints["flat_memory"][0]["cases"]}
    flat_end = {row["case_id"]: row for row in checkpoints["flat_memory"][-1]["cases"]}
    learned_delta = {}
    flat_delta = {}
    for case in cases:
        case_id = case["case_id"]
        learned_delta[case_id] = {
            metric: learned_end[case_id][metric] - learned_start[case_id][metric]
        }
        flat_delta[case_id] = {metric: flat_end[case_id][metric] - flat_start[case_id][metric]}
    return paired_cluster_gap(
        cases, learned_delta, flat_delta, metric, resamples, seed, interval
    )


def exact_discordant_fix_test(cases: list[dict], learned: dict, flat: dict,
                              metric: str) -> dict:
    clusters = defaultdict(list)
    for case in cases:
        case_id = case["case_id"]
        clusters[case["underlying_fix_id"]].append(
            (float(learned[case_id][metric]), float(flat[case_id][metric]))
        )
    learned_only = flat_only = ties = 0
    for values in clusters.values():
        learned_value = sum(left for left, _right in values) / len(values)
        flat_value = sum(right for _left, right in values) / len(values)
        if learned_value > flat_value:
            learned_only += 1
        elif flat_value > learned_value:
            flat_only += 1
        else:
            ties += 1
    discordant = learned_only + flat_only
    if discordant == 0:
        p_value = 1.0
    else:
        from math import comb

        tail = sum(comb(discordant, index) for index in range(min(learned_only, flat_only) + 1))
        p_value = min(1.0, 2.0 * tail / (2 ** discordant))
    return {
        "underlying_fixes": len(clusters),
        "learned_only": learned_only,
        "flat_only": flat_only,
        "ties": ties,
        "discordant": discordant,
        "two_sided_exact_p": round(p_value, 8),
    }


def evaluate_registered(dataset: dict, checkout: Path, spec: dict, registration: dict,
                        embedder=None, on_ready=None) -> dict:
    graph = build_graph(iter_sources(checkout, tuple(spec["scope"])))
    forbidden = set(registration["base_graph_contract"]["forbidden_relations_before_case_one"])
    assert_clean_base_graph(graph, forbidden)
    nodes = {uid: node.as_row() | {"label": node.label} for uid, node in graph.nodes.items()}
    edges = {key: edge.as_row() for key, edge in graph.edges.items()}
    if embedder is None:
        raise ValueError("a validated local-only embedder is required")
    dense = build_dense_index(nodes, embedder)
    bm25 = BM25Index.from_nodes(nodes)
    params = registration["parameters"]
    rankers = {
        arm: fresh_ranker(
            nodes,
            edges,
            bm25,
            dense,
            embedder,
            params["ranker"],
            QueryCache(),
            {},
        )
        for arm in ARMS
    }
    for name, value in params["text_only_overrides"].items():
        setattr(rankers["text_only"], name, value)
    rows_by_ticket = {
        int(row["ticket"]): row for row in dataset["issues"] if row.get("split") == "train"
    }
    holdout_by_ticket = {
        int(row["ticket"]): row for row in dataset["issues"] if row.get("split") == "test"
    }
    stream = [
        rows_by_ticket[case["ticket"]]
        for group in spec["groups"]
        for case in group["cases"]
    ]
    for ranker in rankers.values():
        ranker.prepare(
            [query_only(issue) for issue in stream]
            + [query_only(issue) for issue in holdout_by_ticket.values()]
        )
    learning = params["learning"]
    learned = rankers["learned_graph"]
    operators = make_operators(
        learned,
        learning["mode"],
        learning["lr"],
        merger_every=learning["merger_every"],
        decay=learning["decay"],
    )
    outcomes = {arm: [] for arm in ARMS}
    operator_totals = Counter()
    learning_enabled = True
    learning_failures = []
    holdout_checkpoints = {arm: [] for arm in ARMS}

    def capture_holdout(group_index: int) -> None:
        for arm in ARMS:
            rows = score_cases(
                rankers[arm], spec["holdout_cases"], holdout_by_ticket, params["top_k"]
            )
            holdout_checkpoints[arm].append(
                {"group_index": group_index, "summary": summarize_case_rows(rows), "cases": rows}
            )

    if on_ready is not None:
        on_ready()
    capture_holdout(0)
    for group in spec["groups"]:
        paired_pending = {}
        for case in group["cases"]:
            issue = rows_by_ticket[case["ticket"]]
            pending = {"issue": issue, "rows": {}}
            for arm in ARMS:
                try:
                    prediction = rankers[arm].predict(issue, k=params["top_k"])
                    ranked = [hit.uid for hit in prediction.hits]
                    files = [hit.file for hit in prediction.hits]
                    metrics = score_issue(
                        ranked, files, issue["gold_functions"], issue["gold_files"]
                    )
                    row = {
                        "case_id": case["case_id"],
                        "ticket": case["ticket"],
                        "underlying_fix_id": case["underlying_fix_id"],
                        "status": "completed",
                        **{metric: metrics[metric] for metric in METRICS},
                    }
                    if arm == "learned_graph":
                        row["learning_status"] = "pending"
                        pending["learned_prediction"] = prediction
                    elif arm == "flat_memory":
                        row["learning_status"] = "pending"
                except Exception as exc:  # retained by the registered failure rule
                    row = {
                        "case_id": case["case_id"],
                        "ticket": case["ticket"],
                        "underlying_fix_id": case["underlying_fix_id"],
                        "status": "harness_error",
                        "error_type": type(exc).__name__,
                        **{metric: 0.0 for metric in METRICS},
                    }
                outcomes[arm].append(row)
                pending["rows"][arm] = row
            paired_pending[case["ticket"]] = pending
        for case in group["cases"]:
            pending = paired_pending[case["ticket"]]
            flat_row = pending["rows"]["flat_memory"]
            learned_row = pending["rows"]["learned_graph"]
            if flat_row["status"] != "completed" or learned_row["status"] != "completed":
                flat_row["learning_status"] = "skipped_unpaired_prediction_failure"
                learned_row["learning_status"] = "skipped_unpaired_prediction_failure"
                continue
            was_enabled = learning_enabled
            learning_enabled, status, applied, error_type = attempt_paired_update(
                rankers["flat_memory"],
                learned,
                pending["issue"],
                pending["learned_prediction"],
                operators,
                learning_enabled,
            )
            flat_row["learning_status"] = status
            learned_row["learning_status"] = status
            operator_totals.update(applied)
            if was_enabled and error_type:
                flat_row["learning_error_type"] = error_type
                learned_row["learning_error_type"] = error_type
                learning_failures.append(
                    {
                        "arms": ["flat_memory", "learned_graph"],
                        "case_id": learned_row["case_id"],
                        "ticket": learned_row["ticket"],
                        "error_type": error_type,
                        "effect": (
                            "both memory-arm states rolled back; this and all later outcomes were "
                            "not learned; later predictions continued from both last good states"
                        ),
                    }
                )
        if group["group_index"] in spec["checkpoint_groups"]:
            capture_holdout(group["group_index"])
    cases = [case for group in spec["groups"] for case in group["cases"]]
    by_arm = {
        arm: {row["case_id"]: row for row in rows} for arm, rows in outcomes.items()
    }
    bootstrap = params["bootstrap"]
    summaries = {}
    for arm, rows in outcomes.items():
        summaries[arm] = summarize_case_rows(rows)
    gaps = {}
    for baseline in ("flat_memory", "frozen_graph", "text_only"):
        gaps[f"learned_graph_minus_{baseline}"] = {
            metric: paired_cluster_gap(
                cases,
                by_arm["learned_graph"],
                by_arm[baseline],
                metric,
                int(bootstrap["resamples"]),
                int(bootstrap["seed"]),
                float(bootstrap["interval"]),
            )
            for metric in METRICS
        }
    final_learned = {
        row["case_id"]: row for row in holdout_checkpoints["learned_graph"][-1]["cases"]
    }
    final_flat = {
        row["case_id"]: row for row in holdout_checkpoints["flat_memory"][-1]["cases"]
    }
    primary = {
        metric: paired_cluster_gap(
            spec["holdout_cases"],
            final_learned,
            final_flat,
            metric,
            int(bootstrap["resamples"]),
            int(bootstrap["seed"]),
            float(bootstrap["interval"]),
        )
        for metric in METRICS
    }
    primary["function_acc@10"]["exact_discordant_fix_test"] = exact_discordant_fix_test(
        spec["holdout_cases"], final_learned, final_flat, "function_acc@10"
    )
    descriptive_changes = {
        metric: holdout_delta_of_deltas(
            holdout_checkpoints,
            spec["holdout_cases"],
            metric,
            int(bootstrap["resamples"]),
            int(bootstrap["seed"]),
            float(bootstrap["interval"]),
        )
        for metric in METRICS
    }
    prediction_failures = sum(
        row["status"] != "completed" for rows in outcomes.values() for row in rows
    ) + sum(
        row["status"] != "completed"
        for checkpoints in holdout_checkpoints.values()
        for checkpoint in checkpoints
        for row in checkpoint["cases"]
    )
    primary_acc = primary["function_acc@10"]
    exact_p = primary_acc["exact_discordant_fix_test"]["two_sided_exact_p"]
    confirmatory_valid = prediction_failures == 0 and not learning_failures
    success = bool(
        confirmatory_valid
        and primary_acc["mean"] > 0
        and primary_acc["lo"] > 0
        and exact_p < 0.05
    )
    decision = (
        "invalid_due_to_failures"
        if not confirmatory_valid
        else ("demonstrated_learning_advantage" if success else "no_demonstrated_learning_advantage")
    )
    return {
        "repository": spec["repository"],
        "snapshot": spec["snapshot"],
        "base_graph": {"nodes": len(nodes), "edges": len(edges), "forbidden_relations": []},
        "arms": outcomes,
        "summaries": summaries,
        "summary_weighting": "case-weighted",
        "curves": {
            arm: curve_points(rows, int(params["rolling_window"]))
            for arm, rows in outcomes.items()
        },
        "paired_cluster_gaps": gaps,
        "paired_estimand_weighting": (
            "equal weight per underlying fix commit after averaging report-level paired differences "
            "within each commit"
        ),
        "operators": dict(sorted(operator_totals.items())),
        "fixed_holdout_checkpoints": holdout_checkpoints,
        "primary_final_holdout_learned_minus_flat": primary,
        "descriptive_holdout_delta_of_deltas": descriptive_changes,
        "learning_failures": learning_failures,
        "prediction_failure_count": prediction_failures,
        "confirmatory_valid": confirmatory_valid,
        "decision": decision,
        "decision_rule_satisfied": success,
        "learning_disabled_after_failure": {
            "flat_memory": not learning_enabled,
            "learned_graph": not learning_enabled,
        },
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--model-snapshot", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("--out already exists; score evidence is immutable")
    registration = json.loads(args.registration.read_text())
    digest = validate_registration(registration, root, args.model_snapshot)
    matches = [item for item in registration["repositories"] if item["repository"] == args.repository]
    if len(matches) != 1:
        parser.error("--repository must name exactly one registered repository")
    spec = matches[0]
    dataset, checkout = verify_repository(spec, root)
    embedder = LocalEmbedder(
        args.model_snapshot, registration["embedding_model"]["model_name"]
    )
    if args.run_receipt.exists():
        parser.error("run receipt already exists; this run id may not be retried")

    def mark_started() -> None:
        args.run_receipt.parent.mkdir(parents=True, exist_ok=True)
        with args.run_receipt.open("x") as output:
            output.write(
                json.dumps(
                    {
                        "run_id": args.run_id,
                        "started_at": datetime.now(timezone.utc).isoformat(),
                        "registration_sha256": digest,
                        "repository": args.repository,
                        "rule": "an interrupted run is retained and may not be retried under this run id",
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    result = evaluate_registered(
        dataset, checkout, spec, registration, embedder=embedder, on_ready=mark_started
    )
    result["run_id"] = args.run_id
    result["registration_sha256"] = digest
    result["evaluator_source_manifest_sha256"] = registration[
        "evaluator_source_manifest_sha256"
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as output:
        output.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"repository": result["repository"], "summaries": result["summaries"]}))


if __name__ == "__main__":
    main()
