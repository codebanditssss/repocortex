"""Pick the HydraDB adapter named by settings."""

from __future__ import annotations

from repocortex.config import Settings
from repocortex.hydradb.bolt import BoltClient
from repocortex.hydradb.hosted import HostedClient


def connect(settings: Settings) -> BoltClient | HostedClient:
    if settings.backend == "hosted":
        client = HostedClient(
            settings.hydradb_url,
            settings.hydradb_api_key,
            settings.hydradb_database,
            settings.hydradb_collection,
        )
    elif settings.backend == "bolt":
        client = BoltClient(
            settings.bolt_uri,
            settings.bolt_user,
            settings.bolt_password,
            settings.bolt_database,
        )
    else:
        raise SystemExit(f"unknown HYDRADB_BACKEND {settings.backend!r} (use bolt or hosted)")
    client.verify()
    return client
