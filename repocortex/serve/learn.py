"""Apply one fix, from a bug report and a unified diff, to a live ranker."""

from __future__ import annotations

from pathlib import Path

from repocortex.learn.compress import PathCompressor
from repocortex.learn.replay import make_operators
from repocortex.mine.commits import hunk_lines
from repocortex.serve.load import locate


def functions_from_diff(diff: str, nodes: dict, limit: int = 8) -> list[str]:
    """Map unified-diff hunks onto function nodes by file and line span."""
    by_file: dict[str, list[int]] = {}
    current = ""
    pending: list[str] = []
    for line in (diff or "").splitlines():
        if line.startswith("+++ "):
            if current:
                new_lines, _old = hunk_lines("\n".join(pending))
                by_file.setdefault(current, []).extend(new_lines)
            pending = []
            path = line[4:].strip()
            if path == "/dev/null":
                current = ""
                continue
            if path.startswith("b/"):
                path = path[2:]
            current = path
            continue
        if current:
            pending.append(line)
    if current:
        new_lines, _old = hunk_lines("\n".join(pending))
        by_file.setdefault(current, []).extend(new_lines)
    scored: list[tuple[int, str]] = []
    for uid, node in nodes.items():
        if (node.get("label") or "") != "Function":
            continue
        path = node.get("file") or ""
        lines = by_file.get(path)
        if not lines:
            continue
        start = int(node.get("start") or 0)
        end = int(node.get("end") or start)
        if start <= 0:
            continue
        overlap = sum(1 for line_no in lines if start <= line_no <= end)
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
