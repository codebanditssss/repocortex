"""Offline scoring of paired fix-run receipts. Never executes receipt commands.

See docs/agent-outcomes.md for the v1 schema, trust boundary, and collection
protocol. Existing agent_eval/agent_bench localization output is not accepted.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
import xml.etree.ElementTree as ET

ARMS = ("baseline", "locate")
TOKEN_KEYS = ("input_uncached", "input_cache_read", "input_cache_write", "output")
METRICS = ("elapsed_s", *TOKEN_KEYS, "input_total", "model_calls", "locate_bug_calls")
STATUSES = ("completed", "error", "timeout", "budget_exhausted")
ERROR_KINDS = ("agent", "tool", "provider", "setup", "test", "other")
MAX_BYTES = 32 * 1024 * 1024
MAX_NUMBER = 2**53 - 1  # Portable, exact JSON counters.


class Invalid(ValueError):
    """A stable diagnostic code, never artifact or provider content."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise Invalid(code)


def fields(value, names: str, label: str) -> dict:
    require(isinstance(value, dict), f"{label}:object_required")
    require(set(value) == set(names.split()), f"{label}:fields")
    return value


def string(value, label: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{label}:string_required")
    return value


def integer(value, label: str, minimum: int = 0) -> int:
    require(type(value) is int and minimum <= value <= MAX_NUMBER, f"{label}:integer_required")
    return value


def seconds(value, label: str, positive: bool = False) -> float:
    require(
        type(value) in (int, float) and abs(value) <= MAX_NUMBER and math.isfinite(value)
        and (value > 0 if positive else value >= 0),
        f"{label}:finite_seconds_required",
    )
    return value


def digest(value, label: str, commit: bool = False) -> str:
    pattern = r"(?:[0-9a-f]{40}|[0-9a-f]{64})" if commit else r"[0-9a-f]{64}"
    require(isinstance(value, str) and re.fullmatch(pattern, value) is not None, f"{label}:digest")
    return value


def strings(value, label: str) -> list:
    require(isinstance(value, list) and bool(value), f"{label}:nonempty_list_required")
    for item in value:
        string(item, label)
    return value


def relative(value, label: str, dot: bool = False) -> str:
    string(value, label)
    path = PurePosixPath(value)
    require(
        not path.is_absolute() and ".." not in path.parts and "\\" not in value
        and str(path) == value and (dot or value != "."),
        f"{label}:relative_path_required",
    )
    return value


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, "json:duplicate_key")
        result[key] = value
    return result


def _bad_constant(_value: str) -> None:
    raise Invalid("json:nonfinite_number")


def decode_json(data: bytes):
    try:
        return json.loads(data, object_pairs_hook=_unique_object, parse_constant=_bad_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, Invalid):
            raise
        raise Invalid("json:malformed") from None


def read_bytes(path: Path) -> bytes:
    try:
        require(path.is_file(), "artifact:not_file")
        require(path.stat().st_size <= MAX_BYTES, "artifact:too_large")
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        require(len(data) <= MAX_BYTES, "artifact:too_large")
        return data
    except OSError:
        raise Invalid("artifact:unreadable") from None


def artifact(reference, root: Path) -> bytes:
    ref = fields(reference, "path sha256", "artifact")
    relative(ref["path"], "artifact.path")
    digest(ref["sha256"], "artifact.sha256")
    try:
        path = (root / ref["path"]).resolve()
    except (OSError, RuntimeError, ValueError):
        raise Invalid("artifact:bad_path") from None
    require(path.is_relative_to(root), "artifact:outside_root")
    data = read_bytes(path)
    require(hashlib.sha256(data).hexdigest() == ref["sha256"], "artifact:hash_mismatch")
    return data


def validate_manifest(manifest) -> dict:
    m = fields(manifest, "schema_version experiment_id data_kind protocol tasks", "manifest")
    require(type(m["schema_version"]) is int and m["schema_version"] == 1, "manifest:version")
    string(m["experiment_id"], "experiment_id")
    require(m["data_kind"] in ("synthetic", "external"), "manifest:data_kind")
    p = fields(
        m["protocol"],
        "agent model config_sha256 environment_sha256 base_tools budget cache_policy locate_snapshot_sha256",
        "protocol",
    )
    for key in ("agent", "model", "cache_policy"):
        string(p[key], f"protocol.{key}")
    for key in ("config_sha256", "environment_sha256", "locate_snapshot_sha256"):
        digest(p[key], f"protocol.{key}")
    tools = strings(p["base_tools"], "protocol.base_tools")
    require(len(set(tools)) == len(tools) and "locate_bug" not in tools, "protocol:base_tools")
    budget = fields(p["budget"], "elapsed_s input_tokens output_tokens model_calls", "budget")
    seconds(budget["elapsed_s"], "budget.elapsed_s", positive=True)
    for key in ("input_tokens", "output_tokens", "model_calls"):
        integer(budget[key], f"budget.{key}", minimum=1)
    require(isinstance(m["tasks"], list) and bool(m["tasks"]), "manifest:tasks_required")
    ids = set()
    for task in m["tasks"]:
        t = fields(task, "task_id repository base_commit prompt_sha256 tests", "task")
        task_id = string(t["task_id"], "task_id")
        require(task_id not in ids, "manifest:duplicate_task_id")
        ids.add(task_id)
        string(t["repository"], "task.repository")
        digest(t["base_commit"], "task.base_commit", commit=True)
        digest(t["prompt_sha256"], "task.prompt_sha256")
        require(isinstance(t["tests"], list) and bool(t["tests"]), "task:tests_required")
        test_ids = set()
        for test in t["tests"]:
            spec = fields(test, "test_id argv cwd timeout_s test_count expected_before", "test")
            test_id = string(spec["test_id"], "test.test_id")
            require(test_id not in test_ids, "task:duplicate_test_id")
            test_ids.add(test_id)
            strings(spec["argv"], "test.argv")
            relative(spec["cwd"], "test.cwd", dot=True)
            seconds(spec["timeout_s"], "test.timeout_s", positive=True)
            integer(spec["test_count"], "test.test_count", minimum=1)
            require(spec["expected_before"] in ("pass", "fail"), "test:expected_before")
        require(any(s["expected_before"] == "fail" for s in t["tests"]), "task:no_regression_test")
    return m


def junit(data: bytes, expected_count: int) -> dict:
    """Count actual testcase elements, not a collector's claimed pass boolean."""
    try:
        document = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Invalid("junit:encoding") from None
    # BOM-less UTF-16/32 can decode as UTF-8 with NULs. Never let XML autodetect it.
    require("\x00" not in document, "junit:encoding")
    encoding = re.match(r"""\ufeff?<\?xml\s+[^?]*\bencoding\s*=\s*(['"])([^'"]+)\1""", document)
    require(encoding is None or encoding[2].lower() == "utf-8", "junit:encoding")
    upper = document.upper()
    require("<!DOCTYPE" not in upper and "<!ENTITY" not in upper, "junit:doctype")
    try:
        root = ET.fromstring(document)
    except (ET.ParseError, ValueError, RecursionError):
        raise Invalid("junit:malformed") from None
    require(root.tag in ("testsuite", "testsuites"), "junit:root")
    for parent in root.iter():
        for child in parent:
            if child.tag in ("failure", "error", "skipped"):
                require(parent.tag == "testcase", "junit:outcome_outside_testcase")
    cases = list(root.iter("testcase"))
    require(len(cases) == expected_count, "junit:test_count")
    identities = []
    counts = Counter()
    for case in cases:
        name = string(case.get("name"), "junit.testcase.name")
        identities.append((case.get("classname", ""), name))
        states = [state for state in ("failure", "error", "skipped") if case.find(state) is not None]
        require(len(states) <= 1, "junit:conflicting_test_state")
        counts[states[0] if states else "passed"] += 1
    require(len(set(identities)) == len(identities), "junit:duplicate_testcase")
    # Reject contradictory suite-level summaries, including suite setup errors.
    for suite in root.iter():
        if suite.tag not in ("testsuite", "testsuites"):
            continue
        descendants = list(suite.iter("testcase"))
        actual = {
            "tests": len(descendants),
            "failures": sum(c.find("failure") is not None for c in descendants),
            "errors": sum(c.find("error") is not None for c in descendants),
            "skipped": sum(c.find("skipped") is not None for c in descendants),
        }
        for key, count in actual.items():
            if key in suite.attrib:
                require(suite.attrib[key] == str(count), "junit:summary_mismatch")
    return {"identities": sorted(identities), **{key: counts[key] for key in ("passed", "failure", "error", "skipped")}}


def command_evidence(command, specs: dict, root: Path) -> dict:
    c = fields(
        command,
        "test_id phase argv cwd timeout_s elapsed_s exit_code timed_out output junit",
        "command",
    )
    require(isinstance(c["test_id"], str) and c["test_id"] in specs, "command:unknown_test")
    require(c["phase"] in ("before", "after"), "command:phase")
    spec = specs[c["test_id"]]
    for key in ("argv", "cwd", "timeout_s"):
        require(type(c[key]) is type(spec[key]) and c[key] == spec[key], f"command:{key}_mismatch")
    seconds(c["elapsed_s"], "command.elapsed_s")
    require(type(c["timed_out"]) is bool, "command:timed_out")
    if c["timed_out"]:
        require(c["exit_code"] is None, "command:timeout_exit_code")
    else:
        require(type(c["exit_code"]) is int, "command:exit_code")
    artifact(c["output"], root)
    report = junit(artifact(c["junit"], root), spec["test_count"]) if c["junit"] is not None else None
    require(report is not None or c["timed_out"] or c["exit_code"] != 0, "command:missing_junit")
    passed = bool(
        not c["timed_out"] and c["exit_code"] == 0 and report
        and report["passed"] == spec["test_count"]
    )
    reproduced = bool(
        not c["timed_out"] and type(c["exit_code"]) is int and c["exit_code"] > 0
        and report and report["failure"] > 0 and report["error"] == report["skipped"] == 0
    )
    return {"passed": passed, "reproduced": reproduced, "junit": report, "elapsed_s": c["elapsed_s"]}


def usage_evidence(reference, root: Path) -> dict:
    payload = fields(decode_json(artifact(reference, root)), "calls", "usage")
    require(isinstance(payload["calls"], list), "usage:calls_required")
    ids = set()
    for call in payload["calls"]:
        fields(call, "request_id " + " ".join(TOKEN_KEYS), "usage.call")
        request_id = string(call["request_id"], "usage.request_id")
        require(request_id not in ids, "usage:duplicate_request_id")
        ids.add(request_id)
        for key in TOKEN_KEYS:
            if call[key] is not None:
                integer(call[key], f"usage.{key}")
    totals = {}
    for key in TOKEN_KEYS:
        values = [c[key] for c in payload["calls"]]
        totals[key] = None if None in values else sum(values)
    inputs = [totals[key] for key in TOKEN_KEYS[:3]]
    totals["input_total"] = None if None in inputs else sum(inputs)
    return {**totals, "model_calls": len(payload["calls"])}


def validate_receipt(receipt, manifest: dict, task: dict, root: Path) -> dict:
    r = fields(
        receipt,
        "schema_version experiment_id task_id arm run_id protocol checkout prompt_sha256 "
        "tools locate_bug_calls status elapsed_s errors transcript patch usage commands",
        "receipt",
    )
    require(type(r["schema_version"]) is int and r["schema_version"] == 1, "receipt:version")
    require(r["experiment_id"] == manifest["experiment_id"], "receipt:experiment_mismatch")
    # Canonical JSON comparison preserves distinctions such as true versus 1.
    require(
        json.dumps(r["protocol"], sort_keys=True) == json.dumps(manifest["protocol"], sort_keys=True),
        "receipt:protocol_mismatch",
    )
    string(r["run_id"], "receipt.run_id")
    checkout = fields(r["checkout"], "checkout_id repository base_commit clean_start isolated", "checkout")
    string(checkout["checkout_id"], "checkout.checkout_id")
    require(checkout["repository"] == task["repository"], "checkout:repository_mismatch")
    require(checkout["base_commit"] == task["base_commit"], "checkout:base_commit_mismatch")
    require(checkout["clean_start"] is True and checkout["isolated"] is True, "checkout:not_isolated_clean")
    require(r["prompt_sha256"] == task["prompt_sha256"], "receipt:prompt_mismatch")
    expected_tools = manifest["protocol"]["base_tools"] + (["locate_bug"] if r["arm"] == "locate" else [])
    require(
        isinstance(r["tools"], list) and all(isinstance(t, str) for t in r["tools"])
        and sorted(r["tools"]) == sorted(expected_tools),
        "receipt:tools_mismatch",
    )
    integer(r["locate_bug_calls"], "receipt.locate_bug_calls")
    require(r["arm"] != "baseline" or r["locate_bug_calls"] == 0, "receipt:baseline_used_locate")
    require(r["status"] in STATUSES, "receipt:status")
    seconds(r["elapsed_s"], "receipt.elapsed_s")
    require(isinstance(r["errors"], list), "receipt:errors_required")
    for error in r["errors"]:
        fields(error, "kind code", "error")
        require(error["kind"] in ERROR_KINDS, "error:kind")
        string(error["code"], "error.code")
    require(r["status"] == "completed" or bool(r["errors"]), "receipt:failure_without_error")
    require(bool(artifact(r["transcript"], root).strip()), "receipt:empty_transcript")
    patch = artifact(r["patch"], root) if r["patch"] is not None else None
    if patch is not None:
        require(
            patch.startswith(b"diff --git ") and all(marker in patch for marker in (b"\n--- ", b"\n+++ ", b"\n@@ ")),
            "receipt:not_unified_patch",
        )
    measurements = {
        "elapsed_s": r["elapsed_s"], "locate_bug_calls": r["locate_bug_calls"],
        **usage_evidence(r["usage"], root),
    }
    specs = {s["test_id"]: s for s in task["tests"]}
    require(isinstance(r["commands"], list), "receipt:commands_required")
    commands = {}
    phases = []
    for command in r["commands"]:
        evidence = command_evidence(command, specs, root)
        key = (command["phase"], command["test_id"])
        require(key not in commands, "receipt:duplicate_command")
        commands[key] = evidence
        phases.append(command["phase"])
    require(phases == sorted(phases, key=("before", "after").index), "receipt:phase_order")
    require(sum(c["elapsed_s"] for c in commands.values()) <= r["elapsed_s"] + 0.001, "receipt:elapsed_inconsistent")
    budget = manifest["protocol"]["budget"]
    budget_known = measurements["input_total"] is not None and measurements["output"] is not None
    tests_passed = False
    outcome = r["status"]
    if r["status"] == "completed":
        for metric, limit in (
            ("elapsed_s", "elapsed_s"), ("input_total", "input_tokens"),
            ("output", "output_tokens"), ("model_calls", "model_calls"),
        ):
            value = measurements[metric]
            require(value is None or value <= budget[limit], f"receipt:budget_exceeded:{metric}")
        require(measurements["model_calls"] > 0, "receipt:no_model_calls")
        require(len(commands) == 2 * len(specs), "receipt:incomplete_test_evidence")
        for test_id, spec in specs.items():
            before, after = commands[("before", test_id)], commands[("after", test_id)]
            require(
                before["reproduced"] if spec["expected_before"] == "fail" else before["passed"],
                "receipt:preflight_did_not_match",
            )
            if after["junit"] is not None:
                require(before["junit"]["identities"] == after["junit"]["identities"], "receipt:test_identity_changed")
        tests_passed = all(commands[("after", test_id)]["passed"] for test_id in specs)
        if not tests_passed:
            outcome = "test_fail"
        elif patch is None:
            outcome = "no_patch"
        elif not budget_known:
            outcome = "budget_unverified"
        else:
            outcome = "pass"
    return {
        "outcome": outcome, "tests_passed": tests_passed, "budget_verified": budget_known,
        "measurements": measurements, "error_kinds": [e["kind"] for e in r["errors"]],
    }


def stats(values: list) -> dict:
    known = [v for v in values if v is not None]
    total = sum(known) if known else None
    complete = len(known) == len(values)
    return {
        "known_n": len(known), "unknown_n": len(values) - len(known),
        "known_total": total,
        "total": total if complete else None,
        "mean": total / len(values) if values and complete else None,
    }


def evaluate(manifest, receipts: list, artifacts: Path) -> dict:
    """Validate every expected slot; duplicates invalidate rather than overwrite."""
    manifest = validate_manifest(manifest)
    require(isinstance(receipts, list), "receipts:list_required")
    artifacts = artifacts.resolve()
    require(artifacts.is_dir(), "artifacts:directory_required")
    tasks = {t["task_id"]: t for t in manifest["tasks"]}
    grouped = defaultdict(list)
    conflicts = defaultdict(list)
    rejected = []
    for index, receipt in enumerate(receipts):
        if not isinstance(receipt, dict):
            rejected.append({"receipt_index": index, "reason": "receipt:object_required"})
            continue
        for label, value in (
            ("run_id", receipt.get("run_id")),
            ("checkout_id", (receipt.get("checkout") or {}).get("checkout_id")
             if isinstance(receipt.get("checkout"), dict) else None),
        ):
            if isinstance(value, str) and value:
                conflicts[(label, value)].append(index)
        task_id, arm = receipt.get("task_id"), receipt.get("arm")
        if not isinstance(task_id, str) or task_id not in tasks or arm not in ARMS:
            rejected.append({"receipt_index": index, "reason": "receipt:unknown_task_or_arm"})
            continue
        grouped[(task_id, arm)].append((index, receipt))
    conflict_indices = defaultdict(list)
    for (label, _value), indices in conflicts.items():
        if len(indices) > 1:
            for index in indices:
                conflict_indices[index].append(f"receipt:reused_{label}")
    rows = []
    for task_id, task in tasks.items():
        row = {"task_id": task_id, "arms": {}}
        for arm in ARMS:
            entries = grouped[(task_id, arm)]
            result = {"state": "missing", "receipt_indices": []}
            if entries:
                result = {"state": "invalid", "receipt_indices": [i for i, _r in entries]}
                reasons = ["receipt:duplicate_task_arm"] if len(entries) > 1 else []
                for index, _receipt in entries:
                    reasons.extend(conflict_indices[index])
                if not reasons:
                    try:
                        result.update(validate_receipt(entries[0][1], manifest, task, artifacts))
                        result["state"] = "valid"
                    except Invalid as exc:
                        reasons.append(str(exc))
                if reasons:
                    result["validation_errors"] = sorted(set(reasons))
            row["arms"][arm] = result
        rows.append(row)
    arms = {}
    for arm in ARMS:
        slots = [r["arms"][arm] for r in rows]
        valid = [s for s in slots if s["state"] == "valid"]
        outcomes = Counter(s["outcome"] for s in valid)
        errors = Counter(kind for s in valid for kind in s["error_kinds"])
        arms[arm] = {
            "expected": len(tasks),
            "receipts_received": sum(len(s["receipt_indices"]) for s in slots),
            **{state: sum(s["state"] == state for s in slots) for state in ("missing", "invalid", "valid")},
            "passed": outcomes["pass"], "failed": len(valid) - outcomes["pass"],
            "outcomes": dict(sorted(outcomes.items())),
            "pass_rate_all_tasks": outcomes["pass"] / len(tasks),
            "pass_rate_valid_receipts": outcomes["pass"] / len(valid) if valid else None,
            "runs_with_errors": sum(bool(s["error_kinds"]) for s in valid),
            "error_events": sum(errors.values()), "errors_by_kind": dict(sorted(errors.items())),
            "measurements_valid_receipts": {k: stats([s["measurements"][k] for s in valid]) for k in METRICS},
        }
    paired = [r for r in rows if all(r["arms"][a]["state"] == "valid" for a in ARMS)]
    both_pass = [r for r in paired if all(r["arms"][a]["outcome"] == "pass" for a in ARMS)]
    pair_counts = Counter()
    for row in paired:
        baseline, locate = (row["arms"][a]["outcome"] == "pass" for a in ARMS)
        pair_counts["both_pass" if baseline and locate else "baseline_only" if baseline else "locate_only" if locate else "both_fail"] += 1
    pair_metrics = {}
    for label, subset in (("all_valid_pairs", paired), ("both_pass_pairs", both_pass)):
        pair_metrics[label] = {
            key: stats([
                None if any(r["arms"][a]["measurements"][key] is None for a in ARMS)
                else r["arms"]["locate"]["measurements"][key] - r["arms"]["baseline"]["measurements"][key]
                for r in subset
            ]) for key in METRICS
        }
    missing_pairs = sum(any(r["arms"][a]["state"] == "missing" for a in ARMS) for r in rows)
    return {
        "schema_version": 1, "experiment_id": manifest["experiment_id"], "data_kind": manifest["data_kind"],
        "scope": "receipt_validation_not_independent_execution",
        "receipts_received": len(receipts), "rejected_receipts": rejected,
        "arms": arms,
        "pairs": {
            "expected": len(tasks), "valid": len(paired), "missing": missing_pairs,
            "invalid": len(tasks) - len(paired) - missing_pairs,
            **{key: pair_counts[key] for key in ("both_pass", "baseline_only", "locate_only", "both_fail")},
            "pass_rate_delta_valid_pairs": (
                (pair_counts["locate_only"] - pair_counts["baseline_only"]) / len(paired) if paired else None
            ),
            "delta_locate_minus_baseline": pair_metrics,
        },
        "per_task": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--receipts", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--out", type=Path, help="New report file, never overwritten; default stdout")
    args = parser.parse_args(argv)
    try:
        manifest = decode_json(read_bytes(args.manifest))
        envelope = fields(decode_json(read_bytes(args.receipts)), "schema_version receipts", "receipts")
        require(type(envelope["schema_version"]) is int and envelope["schema_version"] == 1, "receipts:version")
        report = evaluate(manifest, envelope["receipts"], args.artifacts)
        rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.out is None:
            print(rendered, end="")
        else:
            with args.out.open("x", encoding="utf-8") as stream:
                stream.write(rendered)
    except (Invalid, OSError) as exc:
        # OSError details may contain private paths; artifact bodies are never printed.
        print(f"Cannot evaluate: {exc if isinstance(exc, Invalid) else 'io_error'}", file=sys.stderr)
        return 2
    invalid = bool(report["rejected_receipts"]) or any(a["invalid"] for a in report["arms"].values())
    missing = any(a["missing"] for a in report["arms"].values())
    return 1 if invalid or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
