"""Mine Django fix commits into data/dataset.json."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repocortex.config import Settings
from repocortex.mine.dataset import build_dataset, save_dataset


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    settings = Settings.load(root)
    parser = argparse.ArgumentParser(description="mine Django Fixed # commits")
    parser.add_argument("--limit", type=int, default=settings.limit)
    parser.add_argument("--holdout", type=float, default=settings.holdout)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    out = settings.data_dir / "dataset.json"
    if out.exists() and not args.force:
        print(f"dataset exists at {out} (pass --force to rebuild)")
        return
    if not settings.django_repo.exists():
        raise SystemExit(f"django checkout not found at {settings.django_repo}")
    payload = build_dataset(
        settings.django_repo,
        settings.scope,
        args.limit,
        args.holdout,
        settings.data_dir / "trac",
    )
    save_dataset(out, payload)
    print(f"wrote {out} train={payload['train']} test={payload['test']}")


if __name__ == "__main__":
    main()
