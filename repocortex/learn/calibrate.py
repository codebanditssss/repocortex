"""Choose memory strength from earlier fixes, never the evaluation holdout."""
from __future__ import annotations

from collections import defaultdict

from repocortex.eval.harness import eval_ranker
from repocortex.learn.replay import replay

# Fixed before evaluating a target repository. Default wins exact ties.
MEMORY_STRENGTHS = (0.08, 0.0, 0.04, 0.16, 0.32)


def calibration_split(train: list[dict]) -> tuple[list[dict], list[dict]]:
    """Use the last 30% of training commits for validation; keep commits together."""
    if any(row.get("split") != "train" for row in train):
        raise ValueError("calibration accepts training rows only")
    if len({row["ticket"] for row in train}) != len(train):
        raise ValueError("calibration requires unique training tickets")
    groups = defaultdict(list)
    for row in sorted(train, key=lambda row: (row["time"], row["ticket"])):
        groups[row["commit"]].append(row)
    commits = sorted(groups, key=lambda commit: (min(r["time"] for r in groups[commit]), commit))
    cut = max(1, int(len(commits) * 0.7))
    fit = [row for commit in commits[:cut] for row in groups[commit]]
    validation = [row for commit in commits[cut:] for row in groups[commit]]
    if fit and validation and max(row["time"] for row in fit) > min(row["time"] for row in validation):
        raise ValueError("calibration commit groups overlap in time")
    def query(row):
        return " ".join(((row.get("summary") or row.get("subject") or "") + " " +
                         (row.get("description") or "")).lower().split())
    fit_queries = {query(row) for row in fit} - {""}
    if fit_queries & {query(row) for row in validation}:
        raise ValueError("calibration query overlaps between fit and validation")
    return fit, validation


def calibrate_memory(train: list[dict], ranker_factory) -> dict:
    """Replay each candidate on fit only, then freeze it for validation scoring."""
    fit, validation = calibration_split(train)
    result = {
        "status": "insufficient_sample",
        "selected": {"memory_lam": 0.08},
        "fit_tickets": [row["ticket"] for row in fit],
        "validation_tickets": [row["ticket"] for row in validation],
        "selection_rule": "highest validation strict function accuracy@10, then MRR; default wins exact ties",
        "candidate_memory_strengths": list(MEMORY_STRENGTHS),
        "minimum_fit": 10, "minimum_validation": 5,
        "trials": [],
    }
    if len(fit) < 10 or len(validation) < 5:
        return result
    for strength in MEMORY_STRENGTHS:
        ranker = ranker_factory()
        ranker.memory_lam = strength
        replay(ranker, fit, [], mode="full", points=2)
        observed = {int(row["ticket"]) for row in ranker.memory}
        if observed != {int(row["ticket"]) for row in fit}:
            raise RuntimeError("calibration memory must contain only fit tickets")
        metrics = eval_ranker(ranker, validation)
        result["trials"].append({"memory_lam": strength,
                                 "function_acc@10": metrics["function_acc@10"],
                                 "mrr": metrics["mrr"], "per_issue": metrics["per_issue"]})
    winner = max(result["trials"], key=lambda row: (row["function_acc@10"], row["mrr"]))
    result["selected"] = {"memory_lam": winner["memory_lam"]}
    result["status"] = "completed"
    return result
