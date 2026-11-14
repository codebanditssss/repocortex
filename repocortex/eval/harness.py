"""Score BM25, dense, and frozen-graph rankers on the held-out split."""

from __future__ import annotations

from repocortex.eval.metrics import bootstrap_ci, score_rows, summarize
from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.dense import DenseIndex, Embedder
from repocortex.retrieve.textutil import issue_text


def _rows_from_ranked(issues: list[dict], ranked_for) -> list[dict]:
    rows = []
    for issue in issues:
        ranked = ranked_for(issue)
        rows.append(
            {
                "ranked": [item[0] for item in ranked],
                "files": [item[1] for item in ranked],
                "gold": issue["gold_functions"],
                "gold_files": issue["gold_files"],
                "ticket": int(issue.get("ticket") or 0),
            }
        )
    return rows


def _with_ci(rows: list[dict]) -> dict:
    summary = summarize(rows)
    scored = score_rows(rows)
    summary["ci"] = bootstrap_ci(scored)
    summary["per_issue"] = scored
    return summary


def eval_bm25(index: BM25Index, nodes: dict, issues: list[dict], k: int = 10) -> dict:
    def rank(issue):
        top = index.top(issue_text(issue), k)
        return [(uid, (nodes.get(uid) or {}).get("file", "")) for uid, _score in top]

    return _with_ci(_rows_from_ranked(issues, rank))


def eval_dense(index: DenseIndex, embedder: Embedder, nodes: dict, issues: list[dict], k: int = 10) -> dict:
    def rank(issue):
        vector = embedder.encode_one(issue_text(issue))
        top = index.top(vector, k)
        return [(uid, (nodes.get(uid) or {}).get("file", "")) for uid, _score in top]

    return _with_ci(_rows_from_ranked(issues, rank))


def eval_ranker(ranker, issues: list[dict], k: int = 10) -> dict:
    rows = []
    for index, issue in enumerate(issues, start=1):
        if index % 20 == 0 or index == len(issues):
            print(f"  ranked {index}/{len(issues)}", flush=True)
        pred = ranker.predict(issue, k=k)
        rows.append(
            {
                "ranked": [hit.uid for hit in pred.hits],
                "files": [hit.file for hit in pred.hits],
                "gold": issue["gold_functions"],
                "gold_files": issue["gold_files"],
                "ticket": int(issue.get("ticket") or 0),
            }
        )
    return _with_ci(rows)
