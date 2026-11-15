"""Serve an already-built demo on one host; never rebuild or modify HydraDB."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


def health(url: str) -> dict:
    with urlopen(url, timeout=8) as response:
        value = json.load(response)
    # Do not echo backend exception details or environment configuration.
    return {key: value.get(key) for key in ("mode", "connected")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-port", type=int, default=8765)
    parser.add_argument("--web-port", type=int, default=3101)
    parser.add_argument("--check", action="store_true", help="check running services only")
    args = parser.parse_args()
    if not all(1 <= port <= 65535 for port in (args.api_port, args.web_port)):
        parser.error("ports must be between 1 and 65535")
    if args.api_port == args.web_port:
        parser.error("API and web ports must differ")
    api_url = f"http://127.0.0.1:{args.api_port}"
    web_url = f"http://127.0.0.1:{args.web_port}"
    if args.check:
        try:
            for name, url in (("Python", api_url + "/health"), ("Next", web_url + "/api/status")):
                print(name, json.dumps(health(url)))
        except Exception:
            raise SystemExit("Health check failed; inspect the service logs locally.") from None
        return

    required = ["data/corpus.json", "data/embeddings.npz", "data/learned_state.json",
                "data/learned_state.npz", "web/.next/BUILD_ID",
                "web/node_modules/next/dist/bin/next"]
    missing = [path for path in required if not (ROOT / path).exists()]
    if missing:
        raise SystemExit("Missing required artifacts: " + ", ".join(missing))
    node = shutil.which("node")
    if not node:
        raise SystemExit("Node.js is not on PATH.")
    for port in (args.api_port, args.web_port):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise SystemExit(f"Port {port} is occupied; use --check or choose unused ports.") from None

    children: list[subprocess.Popen] = []

    def stop(_signum=None, _frame=None):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        children.append(subprocess.Popen(
            [sys.executable, "scripts/serve_locate.py", str(args.api_port)], cwd=ROOT))
        deadline = time.monotonic() + 180
        while True:
            if children[0].poll() is not None:
                raise SystemExit("Python service exited during startup; inspect its output.")
            try:
                info = health(api_url + "/health")
                print("Python ready:", json.dumps(info), flush=True)
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise SystemExit("Python health check did not become ready within 180 seconds.") from None
                time.sleep(1)
        env = dict(os.environ, REPOCORTEX_API_URL=api_url)
        children.append(subprocess.Popen(
            [node, "node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1",
             "--port", str(args.web_port)], cwd=ROOT / "web", env=env))
        print(f"Demo: {web_url}/app/locate — Ctrl-C stops only these two child services.", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(1)
        raise SystemExit("A demo service exited; shutting down the other service.")
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()
