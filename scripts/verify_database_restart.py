"""Verify feedback after real HydraDB restarts in a disposable Docker container.

Run: python -m scripts.verify_database_restart > results/database_restart.json
Requires the locally available ghcr.io/hydra-db/hydradb:0.4.0 image. Creates only
its own temporary volume/container, with a random private token and loopback
port. Never connects to configured/production databases or reads runtime data.
Synthetic fixture evidence only; this is not accuracy or load evidence.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import uuid

from repocortex.hydradb.bolt import BoltClient

IMAGE = "ghcr.io/hydra-db/hydradb:0.4.0"


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError(f"isolated Docker operation failed: {args[0]}")
    return result.stdout.strip()


def wait_ready(uri, token):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        client = BoltClient(uri, "neo4j", token)
        try:
            client.verify()
            client.query("MATCH (n:FeedbackRecord) RETURN count(*) AS n")
            return
        except Exception:
            time.sleep(0.5)
        finally:
            client.close()
    raise RuntimeError("disposable HydraDB did not become ready")


def run_phase(uri, token, phase):
    env = {**os.environ, "HYDRADB_BACKEND": "bolt", "HYDRADB_BOLT_URI": uri,
           "HYDRADB_BOLT_USER": "neo4j", "HYDRADB_BOLT_PASSWORD": token,
           "HYDRADB_BOLT_DATABASE": "default"}
    result = subprocess.run([sys.executable, "-m", "scripts.verify_persistent_learning",
        "--phase", phase, "--namespace", "verify-database-restart"],
        capture_output=True, text=True, env=env, timeout=90)
    if result.returncode:
        raise RuntimeError(f"isolated {phase} worker failed; credentials and worker output suppressed")
    return json.loads(result.stdout)


def main():
    logging.getLogger("neo4j").setLevel(logging.CRITICAL)
    name = "repocortex-restart-check-" + uuid.uuid4().hex[:12]
    token = secrets.token_hex(32)
    image_id = docker("image", "inspect", IMAGE, "--format", "{{.Id}}")
    with tempfile.TemporaryDirectory(prefix="repocortex-restart-") as folder:
        (Path(folder) / "store").mkdir()
        (Path(folder) / "cache").mkdir()
        token_file = Path(folder) / "auth-token"
        token_file.write_text(token)
        token_file.chmod(0o600)
        env = {
            "CLOUD_PROVIDER": "local", "LOCAL_PATH": "/data/store",
            "GRAPH_NAMESPACE": "default", "GRAPH_ID": "default", "GRAPH_CELL_ID": "cell-0",
            "GRAPH_CELLS": "cell-0", "GRAPH_NODE_ID": "node-0",
            "GRAPH_BOLT_NODE_ADDRESSES": "node-0=127.0.0.1:7687",
            "GRAPH_ADVERTISED_BOLT_ADDR": "127.0.0.1:7687",
            "GRAPH_DATA_CACHE_DIR": "/data/cache", "GRAPH_DATA_CACHE_PART_BYTES": "4194304",
            "GRAPH_DATA_CACHE_MAX_OPEN_FILES": "512", "GRAPH_AUTH_TOKEN_FILE": "/data/auth-token",
            "GRAPH_ALLOW_PLAINTEXT": "true", "RUST_MIN_STACK": "33554432",
            "GRAPH_USAGE_REPORT_ENABLED": "false",
        }
        try:
            args = ["run", "-d", "--name", name, "--pull", "never", "--user", f"{os.getuid()}:{os.getgid()}",
                    "-p", "127.0.0.1::7687", "-v", f"{folder}:/data:Z"]
            for key, value in env.items():
                args.extend(["-e", f"{key}={value}"])
            docker(*args, IMAGE)
            address = docker("port", name, "7687/tcp")
            if not address.startswith("127.0.0.1:"):
                raise RuntimeError("disposable database must bind only to loopback")
            uri = "bolt://" + address
            wait_ready(uri, token)
            first = run_phase(uri, token, "write")
            docker("stop", "--time", "30", name)
            docker("start", name)
            uri = "bolt://" + docker("port", name, "7687/tcp")
            wait_ready(uri, token)
            graceful = run_phase(uri, token, "reload")
            # Crash the database after confirming graceful recovery. This does not
            # simulate a power loss immediately after a fresh journal commit.
            docker("kill", "--signal", "KILL", name)
            docker("start", name)
            uri = "bolt://" + docker("port", name, "7687/tcp")
            wait_ready(uri, token)
            crash = run_phase(uri, token, "reload")
            checks = {
                "confirmed_function_promoted": first["after"][0]["uid"] == "func:fixture.py:beta" and first["before"] != first["after"],
                "graceful_database_restart_restores_exact_ranking": first["after"] == graceful["before"] == graceful["after"],
                "abrupt_database_restart_restores_exact_ranking": first["after"] == crash["before"] == crash["after"],
                "one_event_replayed_after_each_restart": graceful["loaded"]["replayed"] == crash["loaded"]["replayed"] == 1,
                "duplicate_feedback_is_idempotent": bool(graceful["feedback"].get("skipped")) and bool(crash["feedback"].get("skipped")),
            }
            evidence = {"scope": "synthetic two-function fixture; database and worker restart recovery, not accuracy or capacity",
                "database_image": IMAGE, "database_image_id": image_id,
                "storage": "local Docker bind mount; same storage across database restarts",
                "restart_modes": ["docker stop --time 30 / start", "SIGKILL / start"],
                "limitations": ["Single journal event and single writer; no production database touched.",
                    "SIGKILL occurs after a successful graceful restart; not a power-loss or immediate post-commit crash test.",
                    "Original base scoring fixture is recreated; existing runtime artifacts are not used."],
                "processes": {"write": first, "after_graceful_restart": graceful, "after_abrupt_restart": crash},
                "checks": checks}
        finally:
            docker("rm", "-f", name)
        evidence["checks"]["disposable_container_removed"] = name not in docker("ps", "-a", "--format", "{{.Names}}").splitlines()
    evidence["checks"]["temporary_storage_removed"] = not Path(folder).exists()
    print(json.dumps(evidence, indent=2))
    if not all(evidence["checks"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
