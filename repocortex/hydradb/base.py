"""Shared query result types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QueryResult:
    rows: list[dict]
    row_count: int
    truncated: bool = False
    reported_total: int | None = None

    @classmethod
    def from_rows(cls, rows: list[dict], reported_total: int | None = None) -> "QueryResult":
        total = reported_total
        truncated = total is not None and len(rows) < total
        return cls(rows=rows, row_count=len(rows), truncated=truncated, reported_total=total)


@dataclass
class ExpandHit:
    uid: str
    path: str
    hops: int


@dataclass
class ExpandResult:
    hits: list[ExpandHit] = field(default_factory=list)
    truncated: bool = False
    queries: int = 0


# Relationship types this project writes. Queries interpolate only these.
REL_TYPES = (
    "CONTAINS",
    "DEFINES",
    "CALLS",
    "IMPORTS",
    "INHERITS",
    "TESTED_BY",
    "CO_CHANGED",
    "MENTIONS",
    "RAISES",
    "SHORTCUT",
    "SAME_AS",
    "REFINES",
    "FIXED_IN",
)

LABELS = (
    "Repo",
    "File",
    "Class",
    "Function",
    "Test",
    "Concept",
    "Symptom",
    "Commit",
    "Issue",
    "Episode",
)

NODE_FIELDS = (
    "uid",
    "name",
    "file",
    "qualname",
    "signature",
    "doc",
    "start",
    "end",
    "kind",
)


def check_rel(rel: str) -> str:
    if rel not in REL_TYPES:
        raise ValueError(f"unknown relationship type: {rel}")
    return rel


def check_label(label: str) -> str:
    if label not in LABELS:
        raise ValueError(f"unknown label: {label}")
    return label
