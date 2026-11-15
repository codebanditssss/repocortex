"""Score dense+BM25, frozen graph, and learned graph on the same holdout.

Does not train or tune on the holdout. Uses the saved corpus and memory;
graph_mix and bm25_mix stay at the published values. Repeated ticket IDs
are separate fix-commit rows, paired by position for confidence intervals.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repocortex.eval.harness import eval_ranker
from repocortex.eval.metrics import bootstrap_gap as _bootstrap_gap
from repocortex.graph.export import load_corpus
from repocortex.mine.dataset import load_dataset
from repocortex.retrieve.bm25 import BM25Index
from repocortex.retrieve.dense import Embedder, build_dense_index
from repocortex.retrieve.frozen import EdgeTable
from repocortex.retrieve.hybrid import HybridRanker, QueryCache
from repocortex.serve.load import load_ranker


def _copy(nodes: dict) -> dict:
    return {uid: dict(node) for uid, node in nodes.items()}


def paired_gap(left: list[dict], right: list[dict]) -> dict:
    """Pair the same ordered fix rows; ticket IDs are not unique row IDs."""
    if len(left) != len(right) or any(a.get("ticket") != b.get("ticket") for a, b in zip(left, right)):
        raise ValueError("ranker rows must have matching lengths and ticket order")
    without_ticket = lambda rows: [{k: v for k, v in row.items() if k != "ticket"} for row in rows]
    return _bootstrap_gap(without_ticket(left), without_ticket(right))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--exclude-seen-tickets", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    dataset = load_dataset(root / "data" / "dataset.json")
    holdout = [issue for issue in dataset["issues"] if issue["split"] == "test"]
    train_tickets = {issue["ticket"] for issue in dataset["issues"] if issue["split"] == "train"}
    overlap = sorted({issue["ticket"] for issue in holdout} & train_tickets)
    excluded = sum(issue["ticket"] in train_tickets for issue in holdout)
    if args.exclude_seen_tickets:
        holdout = [issue for issue in holdout if issue["ticket"] not in train_tickets]
    print(f"holdout={len(holdout)}", flush=True)
    nodes, edges = load_corpus(root / "data" / "corpus.json")
    bm25 = BM25Index.from_nodes(nodes)
    embedder = Embedder()
    dense = build_dense_index(nodes, embedder, root / "data" / "embeddings.npz")
    cache = QueryCache()
    shared: dict = {}

    lexical = HybridRanker(_copy(nodes), EdgeTable(edges), bm25, dense, embedder, client=None)
    lexical.graph_mix = 0.0
    lexical.memory_lam = 0.0
    lexical.shortcut_lam = 0.0
    lexical.file_prior_lam = 0.0
    lexical.module_prior_lam = 0.0
    lexical.score_cache = cache
    lexical._vec = shared

    frozen = HybridRanker(_copy(nodes), EdgeTable(edges), bm25, dense, embedder, client=None)
    frozen.score_cache = cache
    frozen._vec = shared

    print("dense+bm25, no graph", flush=True)
    lexical_metrics = eval_ranker(lexical, holdout)
    print("frozen graph", flush=True)
    frozen_metrics = eval_ranker(frozen, holdout)
    print("learned graph", flush=True)
    learned = load_ranker(root)
    learned.score_cache = cache
    learned._vec = shared
    learned_metrics = eval_ranker(learned, holdout)

    payload = {
        "n": len(holdout),
        "methodology": {
            "unit": "chronological fix-commit row",
            "pairing": "same ordered row, not ticket ID",
            "train_test_ticket_overlap": overlap,
            "excluded_seen_ticket_rows": excluded if args.exclude_seen_tickets else 0,
            "duplicate_holdout_tickets": {str(t): n for t, n in Counter(i["ticket"] for i in holdout).items() if n > 1},
            "execution": "offline saved corpus and memory; no retraining; no live database queries",
        },
        "note": (
            "dense+bm25 is the published blend with graph_mix 0 and no memory. "
            "frozen is that blend plus the unlearned one-hop. "
            "learned is the saved replay. Same selected holdout fix rows, scored once; see methodology for overlaps."
        ),
        "dense_bm25": {k: v for k, v in lexical_metrics.items() if k != "per_issue"},
        "frozen": {k: v for k, v in frozen_metrics.items() if k != "per_issue"},
        "learned": {k: v for k, v in learned_metrics.items() if k != "per_issue"},
        "gap_learned_minus_dense_bm25": paired_gap(learned_metrics["per_issue"], lexical_metrics["per_issue"]),
        "gap_learned_minus_frozen": paired_gap(learned_metrics["per_issue"], frozen_metrics["per_issue"]),
        "gap_frozen_minus_dense_bm25": paired_gap(frozen_metrics["per_issue"], lexical_metrics["per_issue"]),
    }
    out = args.output or root / "results" / "lexical_gap.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in payload if k != "note"}, indent=2), flush=True)
    print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
