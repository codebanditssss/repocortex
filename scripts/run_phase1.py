"""Run the phase 1 pipeline: smoke, mine, ingest, baselines, replay."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(script: str, extra: list[str]) -> None:
    cmd = [sys.executable, str(ROOT / "scripts" / script), *extra]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="phase 1 end to end")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force-mine", action="store_true")
    parser.add_argument("--skip-replay", action="store_true")
    args = parser.parse_args()
    _run("smoke_hydradb.py", [])
    mine_args = []
    if args.limit is not None:
        mine_args.extend(["--limit", str(args.limit)])
    if args.force_mine:
        mine_args.append("--force")
    _run("mine_django.py", mine_args)
    _run("build_graph.py", [])
    eval_args = [] if args.skip_replay else ["--replay"]
    _run("run_eval.py", eval_args)


if __name__ == "__main__":
    main()
