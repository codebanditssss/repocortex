"""Apply one fix, from a bug report and a unified diff, to a live ranker."""

from __future__ import annotations

import re
from pathlib import Path

from repocortex.learn.compress import PathCompressor
from repocortex.learn.replay import make_operators
from repocortex.serve.load import locate


def functions_from_diff(diff: str, nodes: dict, limit: int = 8) -> list[str]:
    """Map changed new-file lines, excluding unchanged hunk context.

    Deletion-only blocks map only when both surviving boundary lines belong to
    the same function. Whole-function/boundary deletions require an old snapshot
    and are deliberately not guessed from current line spans.
    """
    by_file: dict[str, set[int]] = {}
    deletions: dict[str, list[tuple[int, int]]] = {}
    current = ""
    new_line = None
    pending_delete = False
    old_remaining = new_remaining = 0

    def finish_deletion():
        nonlocal pending_delete
        if pending_delete and current and new_line is not None:
            deletions.setdefault(current, []).append((new_line - 1, new_line))
        pending_delete = False

    for line in (diff or "").split("\n"):
        if line.startswith("diff --git "):
            finish_deletion()
            current, new_line = "", None
        elif line.startswith("+++ ") and new_line is None:
            path = line[4:].split("\t", 1)[0].strip()
            current = "" if path == "/dev/null" else path.removeprefix("b/")
        elif line.startswith("@@ "):
            finish_deletion()
            match = re.match(r"@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            new_line = int(match.group(2)) if match else None
            old_remaining = int(match.group(1) or 1) if match else 0
            new_remaining = int(match.group(3) or 1) if match else 0
        elif current and new_line is not None:
            if line.startswith("-"):
                pending_delete = True
                old_remaining -= 1
            elif line.startswith("+"):
                # A replacement is represented by its added lines, not old offsets.
                pending_delete = False
                by_file.setdefault(current, set()).add(new_line)
                new_line += 1
                new_remaining -= 1
            elif line.startswith(" "):
                finish_deletion()
                new_line += 1
                old_remaining -= 1
                new_remaining -= 1
            if old_remaining <= 0 and new_remaining <= 0:
                finish_deletion()
                new_line = None
    finish_deletion()
    scored: list[tuple[int, str]] = []
    for uid, node in nodes.items():
        if (node.get("label") or "") != "Function":
            continue
        path = node.get("file") or ""
        lines = by_file.get(path, set())
        removed = deletions.get(path, [])
        if not lines and not removed:
            continue
        start = int(node.get("start") or 0)
        end = int(node.get("end") or start)
        if start <= 0:
            continue
        overlap = sum(1 for line_no in lines if start <= line_no <= end)
        overlap += sum(1 for before, after in removed if start <= before <= after <= end)
        if overlap:
            scored.append((overlap, uid))
    scored.sort(key=lambda item: (-item[0], item[1]))
    picked = []
    for _overlap, uid in scored:
        if uid not in picked:
            picked.append(uid)
        if len(picked) >= limit:
            break
    return picked


def learn_from_fix(ranker, report: str, diff: str, operators=None, state_path: Path | None = None) -> dict:
    """Predict, then learn from the functions the diff touches. The prediction is before the update."""
    if getattr(ranker, "feedback_failed", False):
        raise RuntimeError("feedback application failed; restart to replay the durable journal")
    golds = functions_from_diff(diff, ranker.nodes)
    if not golds:
        return {"learned": [], "predicted_before": locate(ranker, report, k=10), "error": "no functions in the diff matched the graph"}
    from repocortex.serve.feedback import feedback_ticket

    ticket = feedback_ticket(report, diff)
    if any(int(item.get("ticket") or 0) == ticket for item in ranker.memory):
        return {
            "learned": golds,
            "ticket": ticket,
            "skipped": "this report and diff were already learned",
            "predicted_before": [],
        }
    files = sorted({uid.split(":", 2)[1] for uid in golds if uid.count(":") >= 2})
    issue = {
        "ticket": ticket,
        "summary": report or "",
        "description": "",
        "gold_functions": golds,
        "gold_files": files,
    }
    predicted = locate(ranker, report, k=10)
    if operators is None:
        operators = getattr(ranker, "feedback_operators", None)
    if operators is None:
        operators = make_operators(ranker, "full", lr=0.25, merger_every=40)
        for op in operators:
            if isinstance(op, PathCompressor):
                op.hydrate(ranker.edges)
        # Keep below-threshold support and merger progress between local calls.
        # A freshly loaded ranker can hydrate materialized edges, not counters
        # that were never saved; durable restart semantics require the journal.
        ranker.feedback_operators = operators
    from repocortex.learn.replay import learn_one

    journal = getattr(ranker, "feedback_journal", None)
    if journal is not None:
        # Write ahead: a failed graph write must not create an in-memory success.
        # On restart the committed event can be replayed if application crashes.
        journal.append(report, diff, golds)
    try:
        learn_one(ranker, issue, operators)
    except Exception:
        if journal is not None:
            ranker.feedback_failed = True
        raise
    if journal is None and hasattr(ranker, "flush"):
        ranker.flush()
    if journal is None and state_path is not None and hasattr(ranker, "save"):
        ranker.save(state_path)
    return {
        "learned": golds,
        "ticket": ticket,
        "predicted_before": predicted,
        "files": files,
        "persistence": "hydradb feedback journal" if journal is not None else "local snapshot" if state_path is not None else "memory",
    }
