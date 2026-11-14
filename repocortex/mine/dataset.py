"""Build the time-ordered Django issue set and the held-out split."""

from __future__ import annotations

import json
from pathlib import Path

from repocortex.graph.builder import build_graph, iter_sources
from repocortex.mine.commits import gold_functions_for_commit, list_fix_commits, snapshot_sha
from repocortex.mine.trac import fetch_tickets


def snapshot_function_uids(repo: Path, scope: tuple[str, ...]) -> set[str]:
    graph = build_graph(iter_sources(repo, scope))
    return {uid for uid, node in graph.nodes.items() if node.label == "Function"}


def assign_splits(issues: list[dict], holdout: float) -> list[dict]:
    """Split by commit time. The newest `holdout` fraction of commits is test."""
    by_commit: dict[str, list[dict]] = {}
    for issue in issues:
        by_commit.setdefault(issue["commit"], []).append(issue)
    order = sorted(by_commit, key=lambda sha: by_commit[sha][0]["time"])
    if len(order) < 2:
        cut = len(order)
    else:
        cut = int(round(len(order) * (1.0 - holdout)))
        cut = min(max(cut, 1), len(order) - 1)
    train = set(order[:cut])
    for issue in issues:
        issue["split"] = "train" if issue["commit"] in train else "test"
    issues.sort(key=lambda item: (item["time"], item["ticket"]))
    return issues


def build_dataset(
    repo: Path,
    scope: tuple[str, ...],
    limit: int,
    holdout: float,
    cache_dir: Path,
    max_gold: int = 8,
    progress=print,
) -> dict:
    sha = snapshot_sha(repo)
    progress(f"snapshot {sha[:12]} scope={','.join(scope)}")
    snapshot_uids = snapshot_function_uids(repo, scope)
    progress(f"snapshot functions {len(snapshot_uids)}")
    commits = list_fix_commits(repo, scope)
    progress(f"fix commits touching scope {len(commits)}")
    # git log is newest first. Scan until we have enough issues that survive filters.
    cache: dict[tuple[str, str], dict | None] = {}
    kept: list[dict] = []
    scanned = 0
    scan_cap = max(limit * 6, limit)
    for commit in commits:
        if len(kept) >= limit or scanned >= scan_cap:
            break
        scanned += 1
        gold = gold_functions_for_commit(repo, commit["commit"], scope, snapshot_uids, cache)
        if not gold or len(gold) > max_gold:
            continue
        files = sorted({uid.split(":", 2)[1] for uid in gold})
        for ticket in commit["tickets"]:
            kept.append(
                {
                    "ticket": ticket,
                    "commit": commit["commit"],
                    "time": commit["time"],
                    "subject": commit["subject"],
                    "gold_functions": gold,
                    "gold_files": files,
                }
            )
            if len(kept) >= limit:
                break
        if scanned % 25 == 0:
            progress(f"scanned {scanned} commits, kept {len(kept)} issues")
    progress(f"scanned {scanned} commits, kept {len(kept)} issues before text")
    texts = fetch_tickets(cache_dir, sorted({item["ticket"] for item in kept}))
    for issue in kept:
        text = texts.get(issue["ticket"]) or {}
        summary = text.get("summary") or issue["subject"]
        description = text.get("description") or ""
        issue["summary"] = summary
        issue["description"] = description
        issue["text_source"] = text.get("source") or "commit"
    assign_splits(kept, holdout)
    train = sum(1 for item in kept if item["split"] == "train")
    test = sum(1 for item in kept if item["split"] == "test")
    progress(f"dataset train={train} test={test}")
    return {
        "snapshot": sha,
        "scope": list(scope),
        "limit": limit,
        "holdout": holdout,
        "max_gold": max_gold,
        "train": train,
        "test": test,
        "issues": kept,
    }


def save_dataset(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def load_dataset(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
