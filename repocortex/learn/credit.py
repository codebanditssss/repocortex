"""Decide which edges a revealed fix should credit or debit.

Credit edges that carried boost onto a gold function. Debit edges that
carried boost onto a top-k function the lexical score would have left out.
An edge that only sat near the seeds is left alone. A hit that dense and
BM25 already ranked in the top k is left alone too.
"""

from __future__ import annotations


def credit_and_debit(pred, gold: list[str]) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]], list[str]]:
    gold_set = set(gold)
    top = {hit.uid for hit in pred.hits}
    base = set(pred.base_topk)
    credit: list[tuple[str, str, str]] = []
    debit: list[tuple[str, str, str]] = []
    promoted: list[str] = []
    seen_credit: set[tuple[str, str, str]] = set()
    seen_debit: set[tuple[str, str, str]] = set()
    support = getattr(pred, "support_edges", {}) or {}
    for uid, keys in support.items():
        if uid in gold_set:
            for key in keys:
                if key not in seen_credit:
                    credit.append(key)
                    seen_credit.add(key)
            continue
        if uid in top and uid not in base:
            promoted.append(uid)
            for key in keys:
                if key not in seen_credit and key not in seen_debit:
                    debit.append(key)
                    seen_debit.add(key)
    return credit, debit, promoted
