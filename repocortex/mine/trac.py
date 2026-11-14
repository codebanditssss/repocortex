"""Fetch Django Trac ticket text and cache it on disk."""

from __future__ import annotations

import csv
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "repocortex/0.1 (django localization research; cache on disk)"
_WIKI = re.compile(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]")


def clean_text(text: str) -> str:
    text = text.replace("{{{", " ").replace("}}}", " ")
    text = _WIKI.sub(r"\1", text)
    text = text.replace("''", "")
    text = text.replace("`", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:4000]


def _cache_path(cache_dir: Path, ticket: int) -> Path:
    return cache_dir / f"{ticket}.json"


def load_cached(cache_dir: Path, ticket: int) -> dict | None:
    path = _cache_path(cache_dir, ticket)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _store(cache_dir: Path, ticket: int, payload: dict) -> dict:
    cache_dir.mkdir(parents=True, exist_ok=True)
    _cache_path(cache_dir, ticket).write_text(json.dumps(payload), encoding="utf-8")
    return payload


def fetch_tickets(cache_dir: Path, tickets: list[int], batch: int = 20, pause: float = 0.35) -> dict[int, dict]:
    """Return ticket id -> {summary, description, source}."""
    found: dict[int, dict] = {}
    missing: list[int] = []
    for ticket in tickets:
        cached = load_cached(cache_dir, ticket)
        if cached is not None:
            found[ticket] = cached
        else:
            missing.append(ticket)
    for start in range(0, len(missing), batch):
        chunk = missing[start : start + batch]
        rows = _query(chunk)
        got = set()
        for row in rows:
            raw_id = row.get("id") or row.get("\ufeffid") or "0"
            try:
                ticket = int(raw_id)
            except ValueError:
                continue
            payload = {
                "summary": clean_text(row.get("Summary") or row.get("summary") or ""),
                "description": clean_text(row.get("Description") or row.get("description") or ""),
                "source": "trac",
            }
            found[ticket] = _store(cache_dir, ticket, payload)
            got.add(ticket)
        for ticket in chunk:
            if ticket not in got:
                found[ticket] = _store(
                    cache_dir,
                    ticket,
                    {"summary": "", "description": "", "source": "missing"},
                )
        if start + batch < len(missing):
            time.sleep(pause)
    return found


def _query(tickets: list[int]) -> list[dict]:
    params = [("format", "csv"), ("col", "id"), ("col", "summary"), ("col", "description"), ("max", "200")]
    for ticket in tickets:
        params.append(("id", str(ticket)))
    url = "https://code.djangoproject.com/query?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/csv"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8-sig", "replace")
    except (urllib.error.URLError, TimeoutError):
        return []
    return list(csv.DictReader(io.StringIO(raw)))
