"""Trusted local search, diff review and durable confirmed-fix feedback."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from repocortex.config import Settings
from repocortex.hydradb import connect
from repocortex.serve.diff_validation import validate_feedback_diff
from repocortex.serve.feedback import configure_feedback, feedback_digest
from repocortex.serve.learn import functions_from_diff, learn_from_fix
from repocortex.serve.load import load_ranker, locate_report, runtime_directory

ROOT = Path(__file__).resolve().parents[1]


def review(ranker, namespace: str, report: str, diff: str) -> dict:
    validate_feedback_diff(diff)
    mapped = functions_from_diff(diff, ranker.nodes)
    if not mapped:
        raise ValueError("no changed functions match the indexed snapshot; no feedback was written")
    identity = [namespace, ranker.feedback_journal.fingerprint, feedback_digest(report, diff), mapped]
    token = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
    return {"review_token": token, "matched_functions": [
        {"uid": uid, **{key: ranker.nodes[uid].get(key) for key in ("file", "qualname", "start", "end")}}
        for uid in mapped], "diff_sha256": hashlib.sha256(diff.encode()).hexdigest()}


def execute(ranker, command, namespace, report, diff=None, review_token=None):
    receipt = {"command": command, "namespace": namespace,
               "scope": "confirmed-fix feedback; not a held-out accuracy measurement"}
    if command == "search":
        return {**receipt, "search": locate_report(ranker, report, k=10)}
    preview = review(ranker, namespace, report, diff)
    if command == "preview":
        return {**receipt, **preview, "writes": False,
                "instruction": "Review the diff and matched functions; apply with this review_token only if the fix is confirmed."}
    if review_token != preview["review_token"]:
        raise ValueError("review token does not match this report, diff, namespace and runtime; preview again")
    before = locate_report(ranker, report, k=10)
    outcome = learn_from_fix(ranker, report, diff)
    if outcome.get("error"):
        raise ValueError(outcome["error"])
    return {**receipt, **preview, "before": before, "feedback": outcome,
            "after": locate_report(ranker, report, k=10),
            "storage": "hydradb feedback journal", "retained": True}


def read_input(path: Path, limit: int, label: str) -> str:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{label} exceeds {limit} UTF-8 bytes")
    text = data.decode("utf-8")
    if not text.strip():
        raise ValueError(f"{label} must not be empty")
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["search", "preview", "apply"])
    parser.add_argument("--runtime", type=Path, help="runtime root containing data/; defaults to REPOCORTEX_RUNTIME or this checkout")
    parser.add_argument("--namespace", required=True, help="one writer per namespace; retained across runs")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--diff", type=Path)
    parser.add_argument("--review-token", help="token from preview; required for apply")
    parser.add_argument("--output", type=Path, help="new JSON receipt file outside data/; defaults to stdout")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", args.namespace):
        parser.error("namespace must be 1–100 letters, digits, dots, underscores or hyphens")
    if (args.command != "search") != bool(args.diff):
        parser.error("--diff is required for preview/apply and not accepted for search")
    if (args.command == "apply") != bool(args.review_token):
        parser.error("--review-token is required for apply and not accepted for search/preview")
    runtime = runtime_directory(ROOT, args.runtime)
    if args.output:
        resolved = args.output.resolve()
        if any(resolved == folder or folder in resolved.parents
               for folder in ((ROOT / "data").resolve(), runtime / "data")):
            parser.error("output must be outside data/")
        if args.output.exists():
            parser.error("output already exists; choose a new receipt filename")
    client = None
    output = None
    try:
        report = read_input(args.report, 48_000, "report").strip()
        if len(report) > 12_000:
            raise ValueError("report exceeds 12000 characters")
        diff = read_input(args.diff, 256_000, "diff") if args.diff else None
        settings = Settings.load(ROOT)
        if settings.backend != "bolt":
            raise ValueError("confirmed-fix CLI requires the Bolt backend; hosted HTTP is not supported")
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            output = args.output.open("x")
            output.write('{"status": "incomplete", "instruction": "Do not treat this receipt as a successful operation."}\n')
            output.flush()
        ranker = load_ranker(runtime)
        try:
            client = connect(settings)
        except Exception:
            raise ValueError("HydraDB connection failed; check local configuration") from None
        ranker.client = client
        setup = configure_feedback(ranker, args.namespace)
        result = execute(ranker, args.command, args.namespace, report, diff, args.review_token)
        result["journal"] = setup
        encoded = json.dumps(result, indent=2) + "\n"
        if output is not None:
            output.seek(0)
            output.write(encoded)
            output.truncate()
            output.flush()
            print(f"Receipt: {args.output}")
        else:
            print(encoded, end="")
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")
    finally:
        if output is not None:
            output.close()
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
