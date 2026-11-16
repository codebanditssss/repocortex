"""Independent repository replay, using linked GitHub issues rather than commit text.

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


def mine(repo: Path, work: Path, limit: int, repository: str = "pallets/flask",
         scope: tuple[str, ...] = ("src/flask",)) -> tuple[dict, object]:
    owner, name = repository.split("/")
    graph = build_graph(iter_sources(repo, scope))
    uids = {uid for uid, node in graph.nodes.items() if node.label == "Function"}
    log = command("git", "-C", str(repo), "log", "--format=%H%x1f%ct%x1f%s")
    candidates = []
    cache = {}
    seen_prs = set()
    audit = Counter()
    for line in log.splitlines():
        sha, timestamp, subject = line.split("\x1f", 2)
        match = re.search(r"\(#(\d+)\)$", subject) or re.match(r"Merge pull request #(\d+)\b", subject)
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
        if cached.get("prs") != identity or cached.get("repository", "pallets/flask") != repository:
            fields = " ".join(f'p{pr}:pullRequest(number:{pr}){{closingIssuesReferences(first:20){{nodes{{number title body createdAt url}}}}}}' for pr, *_ in batch)
            query = 'query{repository(owner:' + json.dumps(owner) + ',name:' + json.dumps(name) + '){' + fields + '}}'
            response = json.loads(command("gh", "api", "graphql", "-f", "query=" + query))
            if response.get("errors"):
                raise RuntimeError("GitHub GraphQL returned errors")
            cached = {"repository": repository, "prs": identity, "response": response}
            path.write_text(json.dumps(cached))
        for pr, sha, timestamp, gold in batch:
            refs = cached["response"]["data"]["repository"][f"p{pr}"]["closingIssuesReferences"]["nodes"]
            if not refs:
                audit["eligible_prs_without_closing_issue"] += 1
            for issue in refs:
                audit["linked_issue_references"] += 1
                if not issue["url"].startswith(f"https://github.com/{repository}/issues/"):
                    audit["cross_repository_references"] += 1
                    continue
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
                    "pull_request": f"https://github.com/{repository}/pull/{pr}",
                    "gold_functions": gold, "gold_files": sorted({uid.split(":", 2)[1] for uid in gold})})
        print(f"queried {start + len(batch)} PRs; {len(issues)} unique issue reports", flush=True)
    assign_splits(issues, 0.40)
    audit["eligible_pr_commits"] = len(candidates)
    audit["retained_unique_issues"] = len(issues)
    dataset = {"selection_counts": dict(audit), "repository": repository, "snapshot": snapshot_sha(repo), "scope": list(scope), "issues": issues}
    return dataset, graph


def split_audit(dataset: dict) -> dict:
    """Reject label/query overlap before scoring a chronological transfer split."""
    train = [row for row in dataset["issues"] if row["split"] == "train"]
    test = [row for row in dataset["issues"] if row["split"] == "test"]
    def text_hash(row):
        text = " ".join((row["summary"] + " " + row["description"]).lower().split())
        return hashlib.sha256(text.encode()).hexdigest()
    overlaps = {}
    for name, key in (("tickets", lambda r: r["ticket"]),
                      ("commits", lambda r: r["commit"]), ("exact_queries", text_hash)):
        overlaps[name] = sorted({key(row) for row in train} & {key(row) for row in test})
    latest = max((row["time"] for row in train), default=None)
    earliest = min((row["time"] for row in test), default=None)
    chronological = latest is None or earliest is None or latest <= earliest
    if not chronological or any(overlaps.values()):
        raise ValueError("transfer split has chronology or train/holdout overlap")
    return {"train": len(train), "holdout": len(test), "overlap": overlaps,
            "chronological": chronological, "latest_training_fix_unix": latest,
            "earliest_holdout_fix_unix": earliest,
            "query_hash": "sha256 of lowercase whitespace-normalized title and body",
            "feedback": "only training rows passed to learning operators; held-out labels used for scoring only"}


def evaluate(dataset: dict, graph, work: Path, calibrate: bool = False) -> dict:
    from repocortex.eval.harness import eval_bm25, eval_dense, eval_ranker
    from repocortex.learn.replay import replay
    from repocortex.retrieve.bm25 import BM25Index
    from repocortex.retrieve.dense import Embedder, build_dense_index
    from repocortex.retrieve.frozen import EdgeTable
    from repocortex.retrieve.hybrid import HybridRanker
    from scripts.eval_lexical import paired_gap

    audit = split_audit(dataset)
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
    calibration = None
    if calibrate:
        from repocortex.learn.calibrate import calibrate_memory
        calibration = calibrate_memory(train, ranker)
    lexical = ranker()
    lexical.graph_mix = 0.0
    lexical.memory_lam = lexical.shortcut_lam = 0.0
    lexical.file_prior_lam = lexical.module_prior_lam = 0.0
    baselines = {"bm25": eval_bm25(bm25, nodes, test), "dense": eval_dense(dense, embedder, nodes, test), "dense_bm25": eval_ranker(lexical, test)}
    frozen = ranker()
    baselines["frozen"] = eval_ranker(frozen, test)
    learned = ranker()
    if calibration is not None:
        learned.memory_lam = calibration["selected"]["memory_lam"]
    played = replay(learned, train, test, mode="full", points=5, record_prequential=True)
    final = eval_ranker(learned, test)
    observed = {int(row["ticket"]) for row in learned.memory}
    expected = {int(row["ticket"]) for row in train}
    if observed != expected:
        raise RuntimeError("learned memory does not exactly match the training tickets")
    audit["observed_memory_tickets"] = sorted(observed)
    audit["training_only_memory_verified"] = True
    return {"status": "completed", "calibration": calibration, "split_audit": audit, "train": len(train), "holdout": len(test),
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
    parser.add_argument("--repository", default="pallets/flask", help="GitHub owner/name")
    parser.add_argument("--scope", nargs="+", default=["src/flask"], help="source directories in the checkout")
    parser.add_argument("--calibrate", action="store_true",
                        help="choose memory strength using only earlier training fixes; preserve holdout")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        parser.error("--repository must be owner/name")
    args.work.mkdir(parents=True, exist_ok=True)
    if args.dataset:
        dataset = json.loads(args.dataset.read_text())
        if dataset["snapshot"] != snapshot_sha(args.repo):
            raise SystemExit("checkout does not match frozen dataset snapshot")
        graph = build_graph(iter_sources(args.repo, tuple(dataset["scope"])))
    else:
        dataset, graph = mine(args.repo, args.work, args.limit, args.repository, tuple(args.scope))
    encoded = json.dumps(dataset, indent=2)
    (args.work / "dataset.json").write_text(encoded)
    results = evaluate(dataset, graph, args.work, calibrate=args.calibrate)
    results.update({"selection_plan": {"maximum_eligible_pr_commits": args.limit, "holdout_commit_fraction": 0.4, "checkpoint_points": 5},
        "selection_counts": dataset["selection_counts"], "repository": dataset["repository"], "snapshot": dataset["snapshot"],
        "dataset_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
        "sample": [{k: row[k] for k in ("ticket", "url", "pull_request", "commit", "time", "split", "gold_functions")} for row in dataset["issues"]],
        "methodology": {"backend": "offline in-memory structural graph; no HydraDB call", "split": "chronological by fix commit, unique issue IDs, last 40% held out (selected before any scoring to retain at least five held-out reports)", "query": "linked GitHub issue title and current body, truncated to 4000 characters by the shared ranker", "graph": "current source snapshot, scopes " + ", ".join(dataset["scope"]) + "; no co-change or held-out outcome edges", "parameters": ("memory strength selected on chronological training-only validation; all other defaults unchanged" if args.calibrate else "existing Django defaults transferred unchanged, no target-repository tuning"), "limitations": ["Exploratory sample, not a statistically established generalization result.", "Retrospective current snapshot includes code from later fixes; issue bodies may have later edits.", "GitHub closing references may include feature requests, not exclusively bugs.", "Only mapped existing functions and PRs with explicit issue links are retained; selection bias applies.", "Fix diff function mapping is a proxy for fault location, not a human-labelled root cause.", "Does not establish hosted live graph learning or cross-repository generalization."]}})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2))
    args.output.with_name(args.output.stem + "_dataset.json").write_text(encoded)
    print(json.dumps({key: results.get(key) for key in ("status", "train", "holdout", "functions")}), flush=True)


if __name__ == "__main__":
    main()
