"""Tokenize code and ticket text the same way for every ranker."""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for match in _TOKEN.findall(text or ""):
        out.append(match.lower())
        pieces = []
        for part in match.split("_"):
            if not part:
                continue
            bits = _CAMEL.findall(part)
            if len(bits) > 1:
                pieces.extend(bit.lower() for bit in bits if len(bit) >= 2)
            elif "_" in match and len(part) >= 2:
                pieces.append(part.lower())
        out.extend(pieces)
    return out


def issue_text(issue: dict) -> str:
    summary = issue.get("summary") or issue.get("subject") or ""
    description = issue.get("description") or ""
    return f"{summary}\n{description}"[:4000]


def node_text(node: dict) -> str:
    return " ".join(
        [
            node.get("qualname") or "",
            node.get("name") or "",
            node.get("file") or "",
            node.get("signature") or "",
            node.get("doc") or "",
        ]
    )
