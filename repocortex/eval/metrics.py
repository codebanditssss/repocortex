"""Strict localization metrics.

Function Acc@k is 1 only when every gold function is inside the top k.
File Acc@k uses the same rule on the files of those functions.
MRR is the reciprocal rank of the first gold function.
"""

from __future__ import annotations

import numpy as np


def function_hit(ranked: list[str], gold: list[str], k: int) -> int:
    if not gold:
        return 0
    return int(set(gold).issubset(set(ranked[:k])))


def file_hit(ranked_files: list[str], gold_files: list[str], k: int) -> int:
    if not gold_files:
        return 0
    ordered = []
    seen = set()
    for name in ranked_files:
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    return int(set(gold_files).issubset(set(ordered[:k])))


def reciprocal_rank(ranked: list[str], gold: list[str]) -> float:
    wanted = set(gold)
    for index, uid in enumerate(ranked):
        if uid in wanted:
            return 1.0 / (index + 1)
    return 0.0


def summarize(rows: list[dict]) -> dict:
    n = len(rows) or 1
    acc5 = acc10 = file1 = file5 = mrr = 0.0
    for row in rows:
        ranked = row["ranked"]
        files = row["files"]
        gold = row["gold"]
        gold_files = row["gold_files"]
        acc5 += function_hit(ranked, gold, 5)
        acc10 += function_hit(ranked, gold, 10)
        file1 += file_hit(files, gold_files, 1)
        file5 += file_hit(files, gold_files, 5)
        mrr += reciprocal_rank(ranked, gold)
    return {
        "n": len(rows),
        "function_acc@5": acc5 / n,
        "function_acc@10": acc10 / n,
        "file_acc@1": file1 / n,
        "file_acc@5": file5 / n,
        "mrr": mrr / n,
    }


METRIC_NAMES = (
    "function_acc@5",
    "function_acc@10",
    "file_acc@1",
    "file_acc@5",
    "mrr",
)


def score_issue(ranked: list[str], files: list[str], gold: list[str], gold_files: list[str]) -> dict:
    return {
        "function_acc@5": float(function_hit(ranked, gold, 5)),
        "function_acc@10": float(function_hit(ranked, gold, 10)),
        "file_acc@1": float(file_hit(files, gold_files, 1)),
        "file_acc@5": float(file_hit(files, gold_files, 5)),
        "mrr": float(reciprocal_rank(ranked, gold)),
    }


def score_rows(rows: list[dict]) -> list[dict]:
    scored = []
    for row in rows:
        item = score_issue(row["ranked"], row["files"], row["gold"], row["gold_files"])
        if "ticket" in row:
            item["ticket"] = int(row["ticket"])
        scored.append(item)
    return scored


def _metric_matrix(samples: list[dict]) -> np.ndarray:
    if not samples:
        return np.zeros((0, len(METRIC_NAMES)), dtype=np.float64)
    return np.array([[float(sample[name]) for name in METRIC_NAMES] for sample in samples], dtype=np.float64)


def _ci_dict(point: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> dict:
    out = {}
    for index, name in enumerate(METRIC_NAMES):
        out[name] = {
            "mean": round(float(point[index]), 6),
            "lo": round(float(lo[index]), 6),
            "hi": round(float(hi[index]), 6),
        }
    return out


def bootstrap_ci(samples: list[dict], n_boot: int = 1000, seed: int = 7, alpha: float = 0.05) -> dict:
    """Percentile bootstrap of the mean. `lo` and `hi` are the 95% interval."""
    matrix = _metric_matrix(samples)
    n = matrix.shape[0]
    if n == 0:
        zeros = np.zeros(len(METRIC_NAMES))
        return _ci_dict(zeros, zeros, zeros)
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, n, size=(n_boot, n))
    means = matrix[picks].mean(axis=1)
    lo = np.quantile(means, alpha / 2.0, axis=0)
    hi = np.quantile(means, 1.0 - alpha / 2.0, axis=0)
    return _ci_dict(matrix.mean(axis=0), lo, hi)


def bootstrap_gap(
    learned: list[dict],
    baseline: list[dict],
    n_boot: int = 1000,
    seed: int = 7,
    alpha: float = 0.05,
) -> dict:
    """Paired bootstrap of learned minus baseline, aligned by ticket when present."""
    base_by_ticket = {int(row["ticket"]): row for row in baseline if "ticket" in row}
    if base_by_ticket and all("ticket" in row for row in learned):
        paired_learned = []
        paired_base = []
        for row in learned:
            other = base_by_ticket.get(int(row["ticket"]))
            if other is None:
                continue
            paired_learned.append(row)
            paired_base.append(other)
    else:
        paired_learned = list(learned)
        paired_base = list(baseline)
    n = min(len(paired_learned), len(paired_base))
    left = _metric_matrix(paired_learned[:n])
    right = _metric_matrix(paired_base[:n])
    if n == 0:
        zeros = np.zeros(len(METRIC_NAMES))
        return {"n": 0, **_ci_dict(zeros, zeros, zeros)}
    diff = left - right
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, n, size=(n_boot, n))
    means = diff[picks].mean(axis=1)
    lo = np.quantile(means, alpha / 2.0, axis=0)
    hi = np.quantile(means, 1.0 - alpha / 2.0, axis=0)
    return {"n": n, **_ci_dict(diff.mean(axis=0), lo, hi)}
