"""Strict localization metrics.

Function Acc@k is 1 only when every gold function is inside the top k.
File Acc@k uses the same rule on the files of those functions.
MRR is the reciprocal rank of the first gold function.
"""

from __future__ import annotations


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
