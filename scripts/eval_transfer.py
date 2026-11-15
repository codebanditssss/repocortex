"""Independent Flask pilot, using linked GitHub issues rather than commit text.

Requires a local clone and authenticated gh. Never writes the primary dataset or
connects to HydraDB. Run: python -m scripts.eval_transfer --repo work/transfer/flask
This is a retrospective, offline algorithm transfer check, not deployment proof.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess

from repocortex.graph.builder import build_graph, iter_sources
from repocortex.mine.commits import gold_functions_for_commit, snapshot_sha
from repocortex.mine.dataset import assign_splits


def command(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def mine(repo: Path, work: Path, limit: int) -> tuple[dict, object]:
    scope = ("src/flask",)
    graph = build_graph(iter_sources(repo, scope))
    uids = {uid for uid, node in graph.nodes.items() if node.label == "Function"}
    log = command("git", "-C", str(repo), "log", "--format=%H%x1f%ct%x1f%s")
    candidates = []
    cache = {}
    seen_prs = set()
    audit = Counter()
    for line in log.splitlines():
        sha, timestamp, subject = line.split("\x1f", 2)
        match = re.search(r"\(#(\d+)\)$", subject)
        if not match or int(match[1]) in seen_prs:
            continue
        audit["unique_pr_references_scanned"] += 1
        pr = int(match[1])
        seen_prs.add(pr)
        gold = gold_functions_for_commit(repo, sha, scope, uids, cache)
        if not gold or len(gold) > 8:
            audit["unmapped_or_more_than_eight_functions"] += 1
            continue
        candidates.append((pr, sha, int(timestamp), gold))
        if len(candidates) >= limit:
            break
    print(f"eligible PR commits: {len(candidates)}", flush=True)
    issues = []
    seen_issues = set()
    for start in range(0, len(candidates), 15):
        batch = candidates[start:start + 15]
        path = work / f"github-{start}.json"
        # Cache identity includes PR numbers to avoid accidental reuse after new HEAD.
        identity = [row[0] for row in batch]
        cached = json.loads(path.read_text()) if path.exists() else {}
        if cached.get("prs") != identity:
            fields = " ".join(f'p{pr}:pullRequest(number:{pr}){{closingIssuesReferences(first:20){{nodes{{number title body createdAt url}}}}}}' for pr, *_ in batch)
            query = 'query{repository(owner:"pallets",name:"flask"){' + fields + '}}'
            response = json.loads(command("gh", "api", "graphql", "-f", "query=" + query))
            if response.get("errors"):
                raise RuntimeError("GitHub GraphQL returned errors")
            cached = {"prs": identity, "response": response}
            path.write_text(json.dumps(cached))
        for pr, sha, timestamp, gold in batch:
            refs = cached["response"]["data"]["repository"][f"p{pr}"]["closingIssuesReferences"]["nodes"]
            if not refs:
                audit["eligible_prs_without_closing_issue"] += 1
            for issue in refs:
                audit["linked_issue_references"] += 1
                ticket = issue["number"]
                if ticket in seen_issues:
                    audit["duplicate_issue_references"] += 1
                    continue
                if not issue["body"]:
                    audit["empty_issue_body"] += 1
                    continue
                if datetime.fromisoformat(issue["createdAt"].replace("Z", "+00:00")).timestamp() > timestamp:
                    audit["issue_created_after_fix"] += 1
                    continue
                seen_issues.add(ticket)
                issues.append({"ticket": ticket, "commit": sha, "time": timestamp,
                    "summary": issue["title"], "description": issue["body"],
                    "text_source": "github_issue", "url": issue["url"],
                    "pull_request": f"https://github.com/pallets/flask/pull/{pr}",
                    "gold_functions": gold, "gold_files": sorted({uid.split(":", 2)[1] for uid in gold})})
        print(f"queried {start + len(batch)} PRs; {len(issues)} unique issue reports", flush=True)
    assign_splits(issues, 0.40)
    audit["eligible_pr_commits"] = len(candidates)
    audit["retained_unique_issues"] = len(issues)
    dataset = {"selection_counts": dict(audit), "repository": "pallets/flask", "snapshot": snapshot_sha(repo), "scope": list(scope), "issues": issues}
    return dataset, graph


def evaluate(dataset: dict, graph, work: Path) -> dict:
    from repocortex.eval.harness import eval_bm25, eval_dense, eval_ranker
    from repocortex.learn.replay import replay
    from repocortex.retrieve.bm25 import BM25Index
    from repocortex.retrieve.dense import Embedder, build_dense_index
    from repocortex.retrieve.frozen import EdgeTable
    from repocortex.retrieve.hybrid import HybridRanker
    from scripts.eval_lexical import paired_gap

    train = [row for row in dataset["issues"] if row["split"] == "train"]
    test = [row for row in dataset["issues"] if row["split"] == "test"]
    if len(train) < 10 or len(test) < 5:
        return {"status": "insufficient_sample", "train": len(train), "holdout": len(test)}
    nodes = {uid: node.as_row() | {"label": node.label} for uid, node in graph.nodes.items()}
    edges = {key: edge.as_row() for key, edge in graph.edges.items()}
    bm25 = BM25Index.from_nodes(nodes)
    embedder = Embedder()
    # Build from this snapshot every run; never reuse Django embedding cache.
    dense = build_dense_index(nodes, embedder)
    def ranker():
        return HybridRanker({uid: dict(node) for uid, node in nodes.items()}, EdgeTable({key: dict(props) for key, props in edges.items()}), bm25, dense, embedder, client=None)
    lexical = ranker()
    lexical.graph_mix = 0.0
    lexical.memory_lam = lexical.shortcut_lam = 0.0
    lexical.file_prior_lam = lexical.module_prior_lam = 0.0
    baselines = {"bm25": eval_bm25(bm25, nodes, test), "dense": eval_dense(dense, embedder, nodes, test), "dense_bm25": eval_ranker(lexical, test)}
    frozen = ranker()
    baselines["frozen"] = eval_ranker(frozen, test)
    learned = ranker()
    played = replay(learned, train, test, mode="full", points=5, record_prequential=True)
    final = eval_ranker(learned, test)
    return {"status": "completed", "train": len(train), "holdout": len(test),
        "functions": len(dense.uids), "nodes": len(nodes), "edges": len(edges),
        "baselines": baselines, "learned": final, "curve": played["curve"],
        "operators": played["operators"], "params": played["params"],
        "gap_learned_minus_frozen": paired_gap(final["per_issue"], baselines["frozen"]["per_issue"]),
        "gap_learned_minus_dense_bm25": paired_gap(final["per_issue"], baselines["dense_bm25"]["per_issue"])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, help="replay a frozen transfer dataset; repo HEAD must match its snapshot")
    parser.add_argument("--work", type=Path, default=Path("work/transfer"))
    parser.add_argument("--output", type=Path, default=Path("results/transfer_flask.json"))
    parser.add_argument("--limit", type=int, default=120, help="maximum eligible PR commits, fixed before scoring")
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    if args.dataset:
        dataset = json.loads(args.dataset.read_text())
        if dataset["snapshot"] != snapshot_sha(args.repo):
            raise SystemExit("checkout does not match frozen dataset snapshot")
        graph = build_graph(iter_sources(args.repo, tuple(dataset["scope"])))
    else:
        dataset, graph = mine(args.repo, args.work, args.limit)
    encoded = json.dumps(dataset, indent=2)
    (args.work / "dataset.json").write_text(encoded)
    results = evaluate(dataset, graph, args.work)
    results.update({"selection_counts": dataset["selection_counts"], "repository": dataset["repository"], "snapshot": dataset["snapshot"],
        "dataset_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
        "sample": [{k: row[k] for k in ("ticket", "url", "pull_request", "commit", "time", "split", "gold_functions")} for row in dataset["issues"]],
        "methodology": {"backend": "offline in-memory structural graph; no HydraDB call", "split": "chronological by fix commit, unique issue IDs, last 40% held out (selected before any scoring to retain at least five held-out reports)", "query": "linked GitHub issue title and current body, truncated to 4000 characters by the shared ranker", "graph": "current source snapshot, src/flask only; no co-change or held-out outcome edges", "parameters": "existing Django defaults transferred unchanged, no Flask tuning", "limitations": ["Small exploratory sample, not independent benchmark replication.", "Retrospective current snapshot includes code from later fixes; issue bodies may have later edits.", "GitHub closing references may include feature requests, not exclusively bugs.", "Only mapped existing functions and PRs with explicit issue links are retained; selection bias applies.", "Fix diff function mapping is a proxy for fault location, not a human-labelled root cause.", "Does not establish hosted live graph learning or cross-repository generalization."]}})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2))
    args.output.with_name(args.output.stem + "_dataset.json").write_text(encoded)
    print(json.dumps({key: results.get(key) for key in ("status", "train", "holdout", "functions")}), flush=True)


if __name__ == "__main__":
    main()
