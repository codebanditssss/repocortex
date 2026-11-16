"""Validate new feedback patches without changing historical diff label mapping."""
from __future__ import annotations

import re

_HUNK = re.compile(r"@@ -(\d{1,12})(?:,(\d{1,12}))? \+(\d{1,12})(?:,(\d{1,12}))? @@(?:.*)")


def validate_feedback_diff(diff: str) -> None:
    """Require complete unified text hunks before accepting durable feedback.

    This checks patch structure, not whether its old/new contents match a checkout
    or whether the proposed fix is correct. Historical journal replay is unchanged.
    """
    def invalid(reason):
        raise ValueError(f"invalid unified diff: {reason}; no feedback was written")

    if not isinstance(diff, str) or not diff.strip():
        invalid("expected file headers and complete hunks")
    old_path = new_path = None
    active = False
    old_left = new_left = 0
    hunks = changes = 0
    file_hunks = 0
    previous_old_end = previous_new_end = 0
    body_line = False
    for raw in diff.split("\n"):
        line = raw.removesuffix("\r")
        if line == r"\ No newline at end of file":
            if not body_line:
                invalid("newline marker must follow a hunk line")
            body_line = False
            continue
        if active:
            if not line or line[0] not in " +-":
                invalid("hunk ended before its declared line counts")
            marker = line[0]
            old_left -= marker in " -"
            new_left -= marker in " +"
            if old_left < 0 or new_left < 0:
                invalid("hunk body exceeds its declared line counts")
            changes += marker in "+-"
            body_line = True
            active = old_left != 0 or new_left != 0
            continue
        body_line = False
        if line.startswith("diff --git "):
            if old_path is not None and (new_path is None or not file_hunks):
                invalid("file headers need at least one complete text hunk")
            old_path = new_path = None
            file_hunks = 0
            previous_old_end = previous_new_end = 0
        elif line.startswith("--- "):
            if old_path is not None and (new_path is None or not file_hunks):
                invalid("file headers need at least one complete text hunk")
            old_path = line[4:].split("\t", 1)[0].strip()
            new_path = None
            file_hunks = 0
            previous_old_end = previous_new_end = 0
            if not old_path or old_path.startswith('"'):
                invalid("expected an unquoted source path")
        elif line.startswith("+++ "):
            if old_path is None or new_path is not None:
                invalid("expected paired --- and +++ file headers")
            new_path = line[4:].split("\t", 1)[0].strip()
            if not new_path or new_path.startswith('"'):
                invalid("expected an unquoted destination path")
        elif line.startswith("@@"):
            match = _HUNK.fullmatch(line)
            if old_path is None or new_path is None or match is None:
                invalid("expected paired file headers and a valid hunk header")
            old_start, old_count, new_start, new_count = match.groups()
            old_start, new_start = int(old_start), int(new_start)
            old_left, new_left = int(old_count or 1), int(new_count or 1)
            if (old_left and not old_start) or (new_left and not new_start) or not (old_left or new_left):
                invalid("invalid hunk start or empty hunk")
            if old_start < previous_old_end or new_start < previous_new_end:
                invalid("hunks overlap or are out of order")
            if (old_path == "/dev/null" and old_left) or (new_path == "/dev/null" and new_left):
                invalid("new or deleted file hunk has inconsistent counts")
            previous_old_end, previous_new_end = old_start + old_left, new_start + new_left
            active = True
            hunks += 1
            file_hunks += 1
        elif line.startswith(("+", "-", " ")) and line.strip():
            invalid("unexpected content outside a hunk")
        elif line.startswith(("GIT binary patch", "Binary files ")):
            invalid("binary patches are not supported")
        elif line and not line.startswith(("index ", "old mode ", "new mode ", "deleted file mode ",
                                           "new file mode ", "similarity index ", "dissimilarity index ",
                                           "rename from ", "rename to ", "copy from ", "copy to ")):
            invalid("unsupported content outside a text hunk")
    if active or not hunks or not changes or new_path is None or not file_hunks:
        invalid("expected complete text hunks with changed lines")
