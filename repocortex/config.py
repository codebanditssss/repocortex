"""Runtime settings from the environment and an optional .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _scope(value: str) -> tuple[str, ...]:
    parts = tuple(p.strip().strip("/") for p in value.split(",") if p.strip())
    return parts or ("django/db", "django/forms")


@dataclass
class Settings:
    backend: str = "bolt"
    bolt_uri: str = "bolt://127.0.0.1:7687"
    bolt_user: str = "neo4j"
    bolt_password: str = "local-development-token-32-bytes"
    bolt_database: str = "default"
    hydradb_url: str = "https://api.hydradb.com"
    hydradb_api_key: str = ""
    hydradb_database: str = "repocortex"
    hydradb_collection: str = "code"
    django_repo: Path = field(default_factory=lambda: Path("data/django"))
    scope: tuple[str, ...] = ("django/db", "django/forms")
    limit: int = 400
    holdout: float = 0.2
    hops: int = 2
    root: Path = field(default_factory=lambda: Path("."))

    @classmethod
    def load(cls, root: Path | None = None) -> "Settings":
        root = (root or Path.cwd()).resolve()
        _load_dotenv(root / ".env")
        return cls(
            backend=os.environ.get("HYDRADB_BACKEND", "bolt").strip().lower(),
            bolt_uri=os.environ.get("HYDRADB_BOLT_URI", "bolt://127.0.0.1:7687"),
            bolt_user=os.environ.get("HYDRADB_BOLT_USER", "neo4j"),
            bolt_password=os.environ.get(
                "HYDRADB_BOLT_PASSWORD", "local-development-token-32-bytes"
            ),
            bolt_database=os.environ.get("HYDRADB_BOLT_DATABASE", "default"),
            hydradb_url=os.environ.get("HYDRADB_URL", "https://api.hydradb.com").rstrip("/"),
            hydradb_api_key=os.environ.get("HYDRADB_API_KEY", ""),
            hydradb_database=os.environ.get("HYDRADB_DATABASE", "repocortex"),
            hydradb_collection=os.environ.get("HYDRADB_COLLECTION", "code"),
            django_repo=Path(os.environ.get("REPOCORTEX_DJANGO", root / "data" / "django")),
            scope=_scope(os.environ.get("REPOCORTEX_SCOPE", "django/db,django/forms")),
            limit=int(os.environ.get("REPOCORTEX_LIMIT", "400")),
            holdout=float(os.environ.get("REPOCORTEX_HOLDOUT", "0.2")),
            hops=int(os.environ.get("REPOCORTEX_HOPS", "2")),
            root=root,
        )

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def results_dir(self) -> Path:
        return self.root / "results"
