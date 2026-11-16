"""SYNTHETIC receipts only. These tests are not model or fix benchmark results."""

import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.agent_outcome_eval import (
    Invalid,
    decode_json,
    evaluate,
    junit,
    main,
    validate_manifest,
)


class AgentOutcomeEvalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-outcomes-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.serial = 0
        self.manifest = {
            "schema_version": 1,
            "experiment_id": "SYNTHETIC-NOT-A-BENCHMARK",
            "data_kind": "synthetic",
            "protocol": {
                "agent": "synthetic-agent-v1", "model": "synthetic-model-v1",
                "config_sha256": "a" * 64, "environment_sha256": "b" * 64,
                "base_tools": ["shell", "edit"], "cache_policy": "cold-per-run",
                "locate_snapshot_sha256": "c" * 64,
                "budget": {"elapsed_s": 60, "input_tokens": 1000, "output_tokens": 100, "model_calls": 5},
            },
            "tasks": [self.task("SYNTHETIC-1")],
        }

    @staticmethod
    def task(task_id):
        return {
            "task_id": task_id, "repository": "synthetic-local-repository",
            "base_commit": "d" * 40, "prompt_sha256": "e" * 64,
            "tests": [
                {
                    "test_id": name, "argv": ["python", "-m", "pytest", name, "--junitxml=report.xml"],
                    "cwd": ".", "timeout_s": 10, "test_count": 1, "expected_before": expected,
                }
                for name, expected in (("regression", "fail"), ("guard", "pass"))
            ],
        }

    def artifact(self, data):
        if isinstance(data, dict):
            data = json.dumps(data).encode()
        elif isinstance(data, str):
            data = data.encode()
        self.serial += 1
        name = f"synthetic-{self.serial}.artifact"
        (self.root / name).write_bytes(data)
        return {"path": name, "sha256": hashlib.sha256(data).hexdigest()}

    @staticmethod
    def xml(state="pass", name="synthetic_case"):
        content = {"pass": "", "fail": "<failure/>", "error": "<error/>", "skip": "<skipped/>"}[state]
        return f'<testsuite tests="1"><testcase classname="synthetic" name="{name}">{content}</testcase></testsuite>'

    def receipt(self, arm="baseline", task_id="SYNTHETIC-1", after="pass", status="completed"):
        run_id = f"synthetic-{task_id}-{arm}"
        task = next(t for t in self.manifest["tasks"] if t["task_id"] == task_id)
        commands = []
        for phase in ("before", "after"):
            for spec in task["tests"]:
                state = spec["expected_before"] if phase == "before" else after
                commands.append({
                    "test_id": spec["test_id"], "phase": phase,
                    **{k: copy.deepcopy(spec[k]) for k in ("argv", "cwd", "timeout_s")},
                    "elapsed_s": 1, "exit_code": 0 if state in ("pass", "skip") else 1,
                    "timed_out": False,
                    "output": self.artifact(f"SYNTHETIC command log: {state}\n"),
                    "junit": self.artifact(self.xml(state)),
                })
        return {
            "schema_version": 1, "experiment_id": self.manifest["experiment_id"],
            "task_id": task_id, "arm": arm, "run_id": run_id,
            "protocol": copy.deepcopy(self.manifest["protocol"]),
            "checkout": {
                "checkout_id": run_id, "repository": task["repository"],
                "base_commit": task["base_commit"], "clean_start": True, "isolated": True,
            },
            "prompt_sha256": task["prompt_sha256"],
            "tools": self.manifest["protocol"]["base_tools"] + (["locate_bug"] if arm == "locate" else []),
            "locate_bug_calls": 1 if arm == "locate" else 0,
            "status": status, "elapsed_s": 20 if arm == "baseline" else 15,
            "errors": [] if status == "completed" else [{"kind": "provider", "code": "SYNTHETIC_FAILURE"}],
            "transcript": self.artifact("SYNTHETIC transcript, no agent was run\n"),
            "patch": self.artifact(
                "diff --git a/synthetic.py b/synthetic.py\n--- a/synthetic.py\n+++ b/synthetic.py\n"
                "@@ -1 +1 @@\n-SYNTHETIC_BUG\n+SYNTHETIC_FIX\n"
            ),
            "usage": self.artifact({"calls": [{
                "request_id": "synthetic-request",
                "input_uncached": 100, "input_cache_read": 20, "input_cache_write": 10, "output": 30,
            }]}),
            "commands": commands,
        }

    def score(self, receipts):
        return evaluate(self.manifest, receipts, self.root)

    def assert_invalid(self, receipt, reason):
        report = self.score([receipt])
        slot = report["per_task"][0]["arms"][receipt["arm"]]
        self.assertEqual(slot["state"], "invalid")
        self.assertIn(reason, slot["validation_errors"])
        self.assertEqual(report["arms"][receipt["arm"]]["passed"], 0)

    def test_paired_passes_use_ids_not_order_and_separate_cache(self):
        self.manifest["tasks"].append(self.task("SYNTHETIC-2"))
        receipts = [self.receipt(a, t["task_id"]) for t in self.manifest["tasks"] for a in ("baseline", "locate")]
        report = self.score(list(reversed(receipts)))
        self.assertEqual(report["data_kind"], "synthetic")
        self.assertEqual(report["pairs"]["both_pass"], 2)
        self.assertEqual(report["pairs"]["valid"], 2)
        self.assertEqual(report["arms"]["baseline"]["pass_rate_all_tasks"], 1)
        measurements = report["arms"]["baseline"]["measurements_valid_receipts"]
        for key, expected in (
            ("input_uncached", 200), ("input_cache_read", 40),
            ("input_cache_write", 20), ("output", 60), ("input_total", 260),
        ):
            self.assertEqual(measurements[key]["total"], expected)
        delta = report["pairs"]["delta_locate_minus_baseline"]["both_pass_pairs"]
        self.assertEqual(delta["elapsed_s"]["mean"], -5)
        self.assertEqual(delta["input_total"]["mean"], 0)

    def test_failed_fixes_and_provider_errors_are_not_dropped(self):
        self.manifest["tasks"].append(self.task("SYNTHETIC-2"))
        receipts = [
            self.receipt(after="fail"), self.receipt("locate"),
            self.receipt(task_id="SYNTHETIC-2"),
            self.receipt("locate", "SYNTHETIC-2", status="error"),
        ]
        report = self.score(receipts)
        pairs = report["pairs"]
        self.assertEqual((pairs["baseline_only"], pairs["locate_only"]), (1, 1))
        self.assertEqual(pairs["pass_rate_delta_valid_pairs"], 0)
        self.assertEqual(pairs["delta_locate_minus_baseline"]["both_pass_pairs"]["elapsed_s"]["known_n"], 0)
        self.assertIsNone(pairs["delta_locate_minus_baseline"]["both_pass_pairs"]["elapsed_s"]["mean"])
        self.assertEqual(report["arms"]["baseline"]["outcomes"], {"pass": 1, "test_fail": 1})
        self.assertEqual(report["arms"]["locate"]["outcomes"], {"error": 1, "pass": 1})
        self.assertEqual(report["arms"]["locate"]["error_events"], 1)
        self.assertEqual(report["arms"]["locate"]["measurements_valid_receipts"]["elapsed_s"]["known_n"], 2)

    def test_missing_and_invalid_have_full_task_denominator(self):
        self.manifest["tasks"].append(self.task("SYNTHETIC-2"))
        baseline, locate = self.receipt(), self.receipt("locate")
        locate["prompt_sha256"] = "f" * 64
        report = self.score([baseline, locate])
        self.assertEqual(report["arms"]["baseline"]["pass_rate_all_tasks"], 0.5)
        self.assertEqual(report["arms"]["baseline"]["pass_rate_valid_receipts"], 1)
        self.assertEqual(report["arms"]["baseline"]["missing"], 1)
        self.assertEqual(report["arms"]["locate"]["invalid"], 1)
        self.assertEqual(report["pairs"]["missing"], 1)
        self.assertEqual(report["pairs"]["invalid"], 1)
        self.assertIsNone(report["pairs"]["pass_rate_delta_valid_pairs"])

    def test_empty_receipts_have_no_fabricated_zero_measurements(self):
        report = self.score([])
        self.assertEqual(report["arms"]["baseline"]["missing"], 1)
        self.assertEqual(report["arms"]["baseline"]["pass_rate_all_tasks"], 0)
        self.assertIsNone(report["arms"]["baseline"]["measurements_valid_receipts"]["elapsed_s"]["total"])

    def test_duplicates_and_reused_isolation_ids_invalidate_all_affected_slots(self):
        for duplicate in ("task_arm", "run_id", "checkout_id"):
            with self.subTest(duplicate=duplicate):
                baseline, locate = self.receipt(), self.receipt("locate")
                if duplicate == "task_arm":
                    report = self.score([baseline, copy.deepcopy(baseline), locate])
                    self.assertEqual(report["arms"]["baseline"]["invalid"], 1)
                    self.assertEqual(report["arms"]["baseline"]["receipts_received"], 2)
                else:
                    if duplicate == "run_id":
                        locate["run_id"] = baseline["run_id"]
                    else:
                        locate["checkout"]["checkout_id"] = baseline["checkout"]["checkout_id"]
                    report = self.score([baseline, locate])
                    self.assertTrue(all(report["arms"][a]["invalid"] == 1 for a in ("baseline", "locate")))
                self.assertEqual(report["pairs"]["valid"], 0)

    def test_unknown_and_malformed_receipts_are_reported(self):
        unknown = self.receipt()
        unknown["task_id"] = "UNKNOWN"
        report = self.score([unknown, None, {"task_id": [], "arm": {}}])
        self.assertEqual(len(report["rejected_receipts"]), 3)
        self.assertEqual(report["arms"]["baseline"]["missing"], 1)
        self.assert_invalid({"task_id": "SYNTHETIC-1", "arm": "baseline"}, "receipt:fields")

    def test_fairness_and_schema_checks(self):
        cases = (
            ("model", lambda r: r["protocol"].update(model="different"), "receipt:protocol_mismatch"),
            ("tools", lambda r: r["tools"].append("internet"), "receipt:tools_mismatch"),
            ("base", lambda r: r["checkout"].update(base_commit="f" * 40), "checkout:base_commit_mismatch"),
            ("dirty", lambda r: r["checkout"].update(clean_start=False), "checkout:not_isolated_clean"),
            ("shared", lambda r: r["checkout"].update(isolated=False), "checkout:not_isolated_clean"),
            ("locate", lambda r: r.update(locate_bug_calls=1), "receipt:baseline_used_locate"),
            ("experiment", lambda r: r.update(experiment_id="other"), "receipt:experiment_mismatch"),
            ("time", lambda r: r.update(elapsed_s=float("nan")), "receipt.elapsed_s:finite_seconds_required"),
            ("bool", lambda r: r.update(locate_bug_calls=True), "receipt.locate_bug_calls:integer_required"),
            ("missing", lambda r: r.pop("usage"), "receipt:fields"),
        )
        for label, mutate, reason in cases:
            with self.subTest(case=label):
                receipt = self.receipt()
                mutate(receipt)
                self.assert_invalid(receipt, reason)

    def test_completed_runs_must_stay_within_each_budget(self):
        for metric, limit in (("elapsed_s", "elapsed_s"), ("input_total", "input_tokens"),
                              ("output", "output_tokens"), ("model_calls", "model_calls")):
            with self.subTest(metric=metric):
                receipt = self.receipt()
                original = self.manifest["protocol"]["budget"][limit]
                measured = {"elapsed_s": 20, "input_total": 130, "output": 30, "model_calls": 1}[metric]
                self.manifest["protocol"]["budget"][limit] = measured
                receipt["protocol"] = copy.deepcopy(self.manifest["protocol"])
                self.assertEqual(self.score([receipt])["arms"]["baseline"]["passed"], 1)
                self.manifest["protocol"]["budget"][limit] = measured - 1 if measured > 1 else 1
                receipt["protocol"] = copy.deepcopy(self.manifest["protocol"])
                if metric == "model_calls":
                    data = decode_json((self.root / receipt["usage"]["path"]).read_bytes())
                    data["calls"].append({**data["calls"][0], "request_id": "synthetic-second-request"})
                    receipt["usage"] = self.artifact(data)
                self.assert_invalid(receipt, f"receipt:budget_exceeded:{metric}")
                self.manifest["protocol"]["budget"][limit] = original

    def test_timeouts_and_budget_stops_are_valid_failures_with_partial_evidence(self):
        for status in ("error", "timeout", "budget_exhausted"):
            with self.subTest(status=status):
                receipt = self.receipt(status=status)
                receipt.update(commands=[], patch=None, elapsed_s=70)
                receipt["usage"] = self.artifact({"calls": []})
                report = self.score([receipt])
                self.assertEqual(report["arms"]["baseline"]["outcomes"], {status: 1})
                self.assertEqual(report["arms"]["baseline"]["failed"], 1)
                receipt["errors"] = []
                self.assert_invalid(receipt, "receipt:failure_without_error")

    def test_unknown_usage_is_null_not_zero_and_cannot_claim_budget_verified_pass(self):
        receipt = self.receipt()
        receipt["usage"] = self.artifact({"calls": [
            {"request_id": "synthetic-1", "input_uncached": 100, "input_cache_read": None,
             "input_cache_write": 10, "output": 30},
            {"request_id": "synthetic-2", "input_uncached": 50, "input_cache_read": 20,
             "input_cache_write": 5, "output": 10},
        ]})
        report = self.score([receipt])
        self.assertEqual(report["arms"]["baseline"]["outcomes"], {"budget_unverified": 1})
        measurements = report["arms"]["baseline"]["measurements_valid_receipts"]
        self.assertEqual(measurements["input_uncached"]["total"], 150)
        self.assertEqual(measurements["output"]["total"], 40)
        self.assertIsNone(measurements["input_cache_read"]["total"])
        self.assertIsNone(measurements["input_total"]["mean"])
        self.assertEqual(measurements["input_total"]["unknown_n"], 1)
        self.assertTrue(report["per_task"][0]["arms"]["baseline"]["tests_passed"])

    def test_usage_rejects_negative_boolean_and_duplicate_requests(self):
        for value in (-1, True, 0.5):
            receipt = self.receipt()
            call = {"request_id": "synthetic", **dict.fromkeys(
                ("input_uncached", "input_cache_read", "input_cache_write", "output"), 0)}
            call["input_uncached"] = value
            receipt["usage"] = self.artifact({"calls": [call]})
            self.assert_invalid(receipt, "usage.input_uncached:integer_required")
        call["input_uncached"] = 1
        receipt["usage"] = self.artifact({"calls": [call, call]})
        self.assert_invalid(receipt, "usage:duplicate_request_id")

    def test_recovered_errors_count_even_on_success_and_unused_locate_is_allowed(self):
        receipt = self.receipt("locate")
        receipt["locate_bug_calls"] = 0
        receipt["errors"] = [{"kind": "tool", "code": "SYNTHETIC_RECOVERED"}] * 2
        report = self.score([receipt])
        self.assertEqual(report["arms"]["locate"]["passed"], 1)
        self.assertEqual(report["arms"]["locate"]["runs_with_errors"], 1)
        self.assertEqual(report["arms"]["locate"]["errors_by_kind"], {"tool": 2})

    def test_command_specs_sequence_and_complete_evidence_are_required(self):
        cases = (
            (lambda r: r["commands"][0].update(argv=["true"]), "command:argv_mismatch"),
            (lambda r: r["commands"][0].update(cwd="elsewhere"), "command:cwd_mismatch"),
            (lambda r: r["commands"][0].update(timeout_s=11), "command:timeout_s_mismatch"),
            (lambda r: r["commands"].pop(), "receipt:incomplete_test_evidence"),
            (lambda r: r["commands"].append(copy.deepcopy(r["commands"][0])), "receipt:duplicate_command"),
            (lambda r: r["commands"].reverse(), "receipt:phase_order"),
            (lambda r: r.update(elapsed_s=3), "receipt:elapsed_inconsistent"),
        )
        for mutate, reason in cases:
            receipt = self.receipt()
            mutate(receipt)
            self.assert_invalid(receipt, reason)

    def test_preflight_must_reproduce_failure_not_skip_error_or_already_pass(self):
        for state in ("pass", "skip", "error"):
            receipt = self.receipt()
            receipt["commands"][0]["junit"] = self.artifact(self.xml(state))
            receipt["commands"][0]["exit_code"] = 1 if state == "error" else 0
            self.assert_invalid(receipt, "receipt:preflight_did_not_match")

    def test_after_failures_skips_and_errors_are_not_successes(self):
        for state in ("fail", "skip", "error"):
            receipt = self.receipt(after=state)
            self.assertEqual(self.score([receipt])["arms"]["baseline"]["outcomes"], {"test_fail": 1})

    def test_command_timeout_or_crash_is_not_a_pass_even_without_junit(self):
        for timed_out in (True, False):
            receipt = self.receipt()
            receipt["commands"][-1].update(
                timed_out=timed_out, exit_code=None if timed_out else -9, junit=None,
            )
            self.assertEqual(self.score([receipt])["arms"]["baseline"]["outcomes"], {"test_fail": 1})
        receipt["commands"][-1].update(exit_code=0, timed_out=False)
        self.assert_invalid(receipt, "command:missing_junit")

    def test_test_identities_cannot_be_swapped_after_patch(self):
        receipt = self.receipt()
        receipt["commands"][-1]["junit"] = self.artifact(self.xml(name="different_case"))
        self.assert_invalid(receipt, "receipt:test_identity_changed")

    def test_no_patch_is_not_a_completed_fix(self):
        receipt = self.receipt()
        receipt["patch"] = None
        self.assertEqual(self.score([receipt])["arms"]["baseline"]["outcomes"], {"no_patch": 1})
        receipt["patch"] = self.artifact('{"functions": ["synthetic.name"]}')
        self.assert_invalid(receipt, "receipt:not_unified_patch")

    def test_hash_missing_path_traversal_and_symlink_escape(self):
        receipt = self.receipt()
        (self.root / receipt["transcript"]["path"]).write_text("tampered")
        self.assert_invalid(receipt, "artifact:hash_mismatch")
        for path in ("../outside", "/outside", "a/../outside", "a\\outside", "\x00"):
            receipt = self.receipt()
            receipt["transcript"]["path"] = path
            reason = "artifact:bad_path" if path == "\x00" else "artifact.path:relative_path_required"
            self.assert_invalid(receipt, reason)
        receipt = self.receipt()
        (self.root / receipt["transcript"]["path"]).unlink()
        self.assert_invalid(receipt, "artifact:not_file")
        with tempfile.TemporaryDirectory(prefix="synthetic-outside-") as outside:
            target = Path(outside) / "evidence"
            target.write_text("SYNTHETIC outside data")
            (self.root / "escape").symlink_to(target)
            receipt["transcript"]["path"] = "escape"
            self.assert_invalid(receipt, "artifact:outside_root")

    def test_junit_counts_summary_states_and_unsafe_xml(self):
        for data, code in (
            (b"<testsuite/>", "junit:test_count"),
            (b"<testsuite", "junit:malformed"),
            (b"<other/>", "junit:root"),
            (b'<!DOCTYPE testsuite><testsuite/>', "junit:doctype"),
            (b'<testsuite errors="1"><testcase name="x"/></testsuite>', "junit:summary_mismatch"),
            (b'<testsuite><testcase name="x"><failure/><error/></testcase></testsuite>', "junit:conflicting_test_state"),
        ):
            with self.subTest(code=code), self.assertRaisesRegex(Invalid, code):
                junit(data, 1)
        with self.assertRaisesRegex(Invalid, "junit:duplicate_testcase"):
            junit(b'<testsuite><testcase name="x"/><testcase name="x"/></testsuite>', 2)
        receipt = self.receipt()
        receipt["commands"][-1]["junit"] = self.artifact("<testsuite/>")
        self.assert_invalid(receipt, "junit:test_count")

    def test_junit_rejects_outcomes_outside_direct_testcase_children(self):
        for state in ("error", "failure", "skipped"):
            for template in (
                '<testsuite><testcase name="synthetic_case"/>{outcome}</testsuite>',
                '<testsuite errors="0" failures="0" skipped="0">'
                '<testcase name="synthetic_case"/>{outcome}</testsuite>',
                '<testsuites><testsuite><testcase name="synthetic_case"/></testsuite>'
                '{outcome}</testsuites>',
                '<testsuite><testcase name="synthetic_case"/>'
                '<properties>{outcome}</properties></testsuite>',
                '<testsuite><testcase name="synthetic_case">'
                '<properties>{outcome}</properties></testcase></testsuite>',
            ):
                with self.subTest(state=state, template=template):
                    data = template.format(outcome=f"<{state}/>")
                    with self.assertRaisesRegex(Invalid, "junit:outcome_outside_testcase"):
                        junit(data.encode("utf-8"), 1)
                    receipt = self.receipt()
                    # A zero exit code and an apparently passing case must not hide setup errors.
                    receipt["commands"][-1]["junit"] = self.artifact(data)
                    self.assert_invalid(receipt, "junit:outcome_outside_testcase")

    def test_junit_requires_utf8_and_rejects_utf16_dtd_bypass(self):
        for encoding in ("utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-32-le", "utf-32-be"):
            for declaration in ("", '<!DOCTYPE testsuite [<!ENTITY name "synthetic_case">]>'):
                with self.subTest(encoding=encoding, dtd=bool(declaration)):
                    name = "&name;" if declaration else "synthetic_case"
                    data = (declaration + f'<testsuite><testcase name="{name}"/></testsuite>').encode(encoding)
                    with self.assertRaisesRegex(Invalid, "junit:encoding"):
                        junit(data, 1)
                    receipt = self.receipt()
                    receipt["commands"][-1]["junit"] = self.artifact(data)
                    self.assert_invalid(receipt, "junit:encoding")
        with self.assertRaisesRegex(Invalid, "junit:encoding"):
            junit(b'<testsuite><testcase name="\xff"/></testsuite>', 1)

    def test_junit_rejects_non_utf8_encoding_declarations(self):
        for encoding in ("UTF-16", "UTF-32", "ISO-8859-1"):
            with self.subTest(encoding=encoding), self.assertRaisesRegex(Invalid, "junit:encoding"):
                junit(
                    (f'<?xml version="1.0" encoding="{encoding}"?>'
                     '<testsuite><testcase name="synthetic_case"/></testsuite>').encode("utf-8"), 1,
                )

    def test_junit_utf8_unicode_and_dtd_prohibition(self):
        for encoding in ("utf-8", "utf-8-sig"):
            with self.subTest(encoding=encoding):
                data = ('<?xml version="1.0" encoding="UTF-8"?>'
                        '<testsuites><testsuite tests="1" errors="0">'
                        '<testcase name="café_测试"/></testsuite></testsuites>').encode(encoding)
                report = junit(data, 1)
                self.assertEqual(report["passed"], 1)
                self.assertEqual(report["identities"], [("", "café_测试")])
            for declaration in (
                '<!DOCTYPE testsuite [<!ENTITY name "synthetic_case">]>',
                '<!ENTITY name "synthetic_case">',
            ):
                with self.subTest(encoding=encoding, declaration=declaration):
                    with self.assertRaisesRegex(Invalid, "junit:doctype"):
                        junit((declaration + self.xml()).encode(encoding), 1)

    def test_manifest_rejects_ambiguous_or_non_fix_tasks_and_old_localization_format(self):
        for mutate, reason in (
            (lambda m: m["tasks"].append(copy.deepcopy(m["tasks"][0])), "manifest:duplicate_task_id"),
            (lambda m: m["tasks"][0]["tests"][0].update(expected_before="pass"), "task:no_regression_test"),
            (lambda m: m.update(tasks=[]), "manifest:tasks_required"),
            (lambda m: m.update(schema_version=True), "manifest:version"),
            (lambda m: m["protocol"]["base_tools"].append("locate_bug"), "protocol:base_tools"),
        ):
            manifest = copy.deepcopy(self.manifest)
            mutate(manifest)
            with self.assertRaisesRegex(Invalid, reason):
                validate_manifest(manifest)
        with self.assertRaisesRegex(Invalid, "manifest:fields"):
            validate_manifest({"tasks": [{"ticket": 1, "gold_functions": ["synthetic"]}]})

    def test_strict_json_and_cli_error_codes(self):
        for data in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b"\xff", b"{"):
            with self.assertRaises(Invalid):
                decode_json(data)
        manifest_path, receipts_path = self.root / "manifest.json", self.root / "receipts.json"
        manifest_path.write_text(json.dumps(self.manifest))
        receipts_path.write_text(json.dumps({"schema_version": 1, "receipts": []}))
        argv = ["--manifest", str(manifest_path), "--receipts", str(receipts_path), "--artifacts", str(self.root)]
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(argv), 1)
        self.assertEqual(json.loads(output.getvalue())["arms"]["locate"]["missing"], 1)
        receipts_path.write_text("{}")
        with redirect_stderr(io.StringIO()) as error:
            self.assertEqual(main(argv), 2)
        self.assertIn("receipts:fields", error.getvalue())

    def test_real_cli_fresh_process_scores_failure_and_refuses_overwrite(self):
        receipts = [self.receipt(after="fail"), self.receipt("locate")]
        manifest_path, receipts_path = self.root / "manifest.json", self.root / "receipts.json"
        manifest_path.write_text(json.dumps(self.manifest))
        receipts_path.write_text(json.dumps({"schema_version": 1, "receipts": receipts}))
        script = Path(__file__).resolve().parents[1] / "scripts" / "agent_outcome_eval.py"
        command = [
            sys.executable, str(script), "--manifest", str(manifest_path),
            "--receipts", str(receipts_path), "--artifacts", str(self.root),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=10, cwd=self.root)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["pairs"]["locate_only"], 1)
        self.assertEqual(report["scope"], "receipt_validation_not_independent_execution")
        output = self.root / "report.json"
        written = subprocess.run(command + ["--out", str(output)], capture_output=True, text=True, timeout=10)
        self.assertEqual(written.returncode, 0, written.stderr)
        original = output.read_bytes()
        refused = subprocess.run(command + ["--out", str(output)], capture_output=True, text=True, timeout=10)
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
