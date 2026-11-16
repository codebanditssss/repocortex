"""Shared edge-weight decoding for persisted and in-memory graph rows."""
from __future__ import annotations


def edge_weight(props: dict, default: float = 1.0) -> float:
    """Use the fallback only for absent/null weights; zero is a real weight."""
    value = props.get("w")
    return float(default if value is None else value)
