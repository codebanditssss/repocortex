"""Where plain dense search puts a held-out fix, next to the RepoCortex top hit.

python scripts/dense_rank.py 36865 35870
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repocortex.retrieve.dense import Embedder  # noqa: E402
from repocortex.retrieve.textutil import issue_text  # noqa: E402


def main(tickets: list[int]) -> None:
    blob = np.load("data/embeddings.npz")
    uids = blob["uids"].tolist()
    matrix = blob["matrix"]
    issues = {}
    for issue in json.loads(Path("data/dataset.json").read_text())["issues"]:
        if issue["split"] != "train":
            issues.setdefault(issue["ticket"], issue)
    prov = {p["ticket"]: p for p in json.loads(Path("results/provenance.json").read_text())["issues"]}
    embedder = Embedder()
    for ticket in tickets:
        issue, record = issues[ticket], prov[ticket]
        sims = matrix @ embedder.encode_one(issue_text(issue))
        order = np.argsort(-sims)
        rank = {uids[j]: r + 1 for r, j in enumerate(order)}
        print(f"#{ticket} {issue['summary']}")
        for gold in record["gold"]:
            print(f"  gold {gold.split(':')[-1]}  dense rank {rank.get(gold, '-')}")
        top = record["hits"][0]
        print(f"  repocortex #1 {top['uid'].split(':')[-1]} gold={top['gold']}")
        print(f"  path {top['path']}")


if __name__ == "__main__":
    main([int(t.lstrip("#")) for t in sys.argv[1:]] or [36865])
