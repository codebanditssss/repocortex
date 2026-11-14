"""Mine Django commits whose message is 'Fixed #NNNN'."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from repocortex.graph.builder import functions_touching, parse_source

TICKET_RE = re.compile(r"Fixed #(\d+)", re.IGNORECASE)
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def hunk_lines(diff: str) -> tuple[list[int], list[int]]:
    """Return (new-file lines, old-file lines) covered by a unified diff."""
    new_lines: list[int] = []
    old_lines: list[int] = []
    for line in diff.splitlines():
        match = HUNK_RE.match(line)
        if not match:
            continue
        old_start = int(match.group(1))
        old_len = 1 if match.group(2) is None else int(match.group(2))
        new_start = int(match.group(3))
        new_len = 1 if match.group(4) is None else int(match.group(4))
        if new_len > 0:
            new_lines.extend(range(new_start, new_start + new_len))
        if old_len > 0:
            old_lines.extend(range(old_start, old_start + old_len))
    return new_lines, old_lines


def _run(repo: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
    )


def snapshot_sha(repo: Path) -> str:
    result = _run(repo, ["rev-parse", "HEAD"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode()[:300])
    return result.stdout.decode().strip()


def list_fix_commits(repo: Path, scope: tuple[str, ...]) -> list[dict]:
    result = _run(
        repo,
        [
            "log",
            "--regexp-ignore-case",
            "--grep",
            r"Fixed #[0-9]",
            "--format=%H%x1f%ct%x1f%s",
            "--",
            *scope,
        ],
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode()[:300])
    commits = []
    for line in result.stdout.decode("utf-8", "replace").splitlines():
        sha, time_s, subject = line.split("\x1f", 2)
        tickets = [int(n) for n in TICKET_RE.findall(subject)]
        if not tickets:
            continue
        commits.append(
            {
                "commit": sha,
                "time": int(time_s),
                "subject": subject.strip(),
                "tickets": tickets,
            }
        )
    return commits


def _show(repo: Path, rev: str, path: str) -> str | None:
    result = _run(repo, ["show", f"{rev}:{path}"])
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", "replace")


def _changed_paths(repo: Path, parent: str, commit: str, scope: tuple[str, ...]) -> list[str]:
    result = _run(repo, ["diff", "--name-only", parent, commit, "--", *scope])
    if result.returncode != 0:
        return []
    paths = []
    for line in result.stdout.decode().splitlines():
        path = line.strip()
        if not path.endswith(".py") or "/migrations/" in f"/{path}":
            continue
        paths.append(path)
    return paths


def gold_functions_for_commit(
    repo: Path,
    commit: str,
    scope: tuple[str, ...],
    snapshot_uids: set[str],
    cache: dict[tuple[str, str], dict | None],
) -> list[str]:
    parent_res = _run(repo, ["rev-parse", f"{commit}^"])
    if parent_res.returncode != 0:
        return []
    parent = parent_res.stdout.decode().strip()
    found: set[str] = set()
    for path in _changed_paths(repo, parent, commit, scope):
        diff = _run(repo, ["diff", "-U0", parent, commit, "--", path])
        if diff.returncode != 0:
            continue
        new_lines, old_lines = hunk_lines(diff.stdout.decode("utf-8", "replace"))
        if new_lines:
            key = (commit, path)
            if key not in cache:
                source = _show(repo, commit, path)
                cache[key] = parse_source(path, source) if source is not None else None
            found.update(uid for uid in functions_touching(cache[key] or {}, new_lines) if uid in snapshot_uids)
        if old_lines:
            key = (parent, path)
            if key not in cache:
                source = _show(repo, parent, path)
                cache[key] = parse_source(path, source) if source is not None else None
            found.update(uid for uid in functions_touching(cache[key] or {}, old_lines) if uid in snapshot_uids)
    return sorted(found)
