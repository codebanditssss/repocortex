import copy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from scripts.register_prequential_track1 import (
    DEFAULT_PARAMETERS,
    audit_cross_split,
    build_registration,
    canonical_json,
    chronological_groups,
)
from scripts.run_prequential_track1 import (
    attempt_paired_update,
    assert_clean_base_graph,
    curve_points,
    paired_cluster_gap,
    query_only,
    validate_registration,
)
from repocortex.learn.base import OperatorResult
from repocortex.retrieve.frozen import EdgeTable, Hit, Prediction


def issue(ticket, commit, time, text, split="train"):
    return {
        "ticket": ticket,
        "commit": commit,
        "time": time,
        "split": split,
        "summary": text,
        "description": "details " + text,
        "gold_functions": ["func:src/app.py:app.run"],
        "gold_files": ["src/app.py"],
    }


def dataset(snapshot):
    return {
        "repository": "owner/repo",
        "snapshot": snapshot,
        "scope": ["src"],
        "issues": [
            issue(3, "b" * 40, 20, "third"),
            issue(1, "a" * 40, 10, "first"),
            issue(2, "a" * 40, 10, "second"),
            issue(4, "c" * 40, 30, "held out", split="test"),
        ],
    }


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def make_repo(tmp_path):
    root = tmp_path / "study"
    checkout = root / "checkout"
    source = checkout / "src" / "app.py"
    source.parent.mkdir(parents=True)
    source.write_text("def run():\n    return 1\n")
    git(checkout, "init", "-q")
    git(checkout, "add", ".")
    git(checkout, "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-qm", "snapshot")
    snapshot = git(checkout, "rev-parse", "HEAD")
    data = root / "dataset.json"
    data.write_text(json.dumps(dataset(snapshot)))
    evaluator = root / "runner.py"
    evaluator.write_text("# frozen evaluator\n")
    model = root / "model-snapshot" / "revision-1"
    model.mkdir(parents=True)
    (model / "config.json").write_text("{}\n")
    git(root, "init", "-q")
    git(root, "add", "dataset.json", "runner.py")
    git(root, "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-qm", "study")
    return root, checkout, data, evaluator, model


def test_groups_same_fix_before_later_commit_and_excludes_holdout():
    groups = chronological_groups(dataset("f" * 40))
    assert [[case["ticket"] for case in group["cases"]] for group in groups] == [[1, 2], [3]]
    assert groups[0]["underlying_fix_id"] == "owner/repo@" + "a" * 40


def test_groups_reject_inconsistent_time_for_one_fix():
    value = dataset("f" * 40)
    value["issues"][1]["time"] = 11
    with pytest.raises(ValueError, match="multiple timestamps"):
        chronological_groups(value)


@pytest.mark.parametrize("kind", ["ticket", "commit", "exact_query", "near_duplicate"])
def test_cross_split_audit_rejects_overlap_and_near_duplicates(kind):
    value = dataset("f" * 40)
    train = value["issues"][1]
    holdout = value["issues"][3]
    if kind == "ticket":
        holdout["ticket"] = train["ticket"]
    elif kind == "commit":
        holdout["commit"] = train["commit"]
    elif kind == "exact_query":
        holdout["summary"] = train["summary"]
        holdout["description"] = train["description"]
    else:
        train["summary"] = "alpha beta gamma delta epsilon zeta eta"
        train["description"] = ""
        holdout["summary"] = "alpha beta gamma delta epsilon zeta theta"
        holdout["description"] = ""
    with pytest.raises(ValueError, match="overlap|near-duplicate"):
        audit_cross_split(value)


def test_prepare_payload_contains_query_fields_only():
    value = issue(1, "a" * 40, 1, "query")
    assert query_only(value) == {
        "ticket": 1,
        "summary": "query",
        "description": "details query",
    }


def test_registration_freezes_inputs_sources_parameters_and_failure_rules(tmp_path):
    root, checkout, data, evaluator, model = make_repo(tmp_path)
    registration = build_registration(
        [(data, checkout)], [evaluator], root, model, sentinel_sha256="a" * 64
    )
    spec = registration["repositories"][0]
    assert spec["case_count"] == 3
    assert spec["fix_group_count"] == 2
    assert spec["dataset"]["sha256"] == hashlib.sha256(data.read_bytes()).hexdigest()
    assert spec["source_manifest"][0]["path"] == "src/app.py"
    assert registration["parameters"] == DEFAULT_PARAMETERS
    assert "no retry" in registration["execution_contract"]["failures"]
    assert registration["registration_sha256"]


def test_registration_digest_and_evaluator_hash_are_verified(tmp_path, monkeypatch):
    root, checkout, data, evaluator, model = make_repo(tmp_path)
    registration = build_registration(
        [(data, checkout)], [evaluator], root, model, sentinel_sha256="a" * 64
    )
    monkeypatch.setattr(
        "scripts.run_prequential_track1.embedding_sentinel_sha256", lambda _path: "a" * 64
    )
    assert validate_registration(registration, root, model) == registration["registration_sha256"]
    evaluator.write_text("# changed\n")
    with pytest.raises(ValueError, match="evaluator source mismatch"):
        validate_registration(registration, root, model)


def test_registration_digest_rejects_protocol_changes(tmp_path, monkeypatch):
    root, checkout, data, evaluator, model = make_repo(tmp_path)
    registration = build_registration(
        [(data, checkout)], [evaluator], root, model, sentinel_sha256="a" * 64
    )
    changed = copy.deepcopy(registration)
    changed["parameters"]["top_k"] = 5
    monkeypatch.setattr(
        "scripts.run_prequential_track1.embedding_sentinel_sha256", lambda _path: "a" * 64
    )
    with pytest.raises(ValueError, match="registration digest mismatch"):
        validate_registration(changed, root, model)


def test_base_graph_rejects_outcome_relations():
    clean = type("Graph", (), {"edges": {("a", "CALLS", "b"): {}}})()
    assert_clean_base_graph(clean, {"FIXED_IN", "SHORTCUT"})
    leaked = type("Graph", (), {"edges": {("i", "FIXED_IN", "f"): {}}})()
    with pytest.raises(ValueError, match="outcome-derived"):
        assert_clean_base_graph(leaked, {"FIXED_IN", "SHORTCUT"})


def test_curve_is_cumulative_and_trailing_window():
    rows = [
        {"case_id": "a", "ticket": 1, "function_acc@10": 0, "mrr": 0},
        {"case_id": "b", "ticket": 2, "function_acc@10": 1, "mrr": 0.5},
        {"case_id": "c", "ticket": 3, "function_acc@10": 1, "mrr": 1},
    ]
    points = curve_points(rows, 2)
    assert points[-1]["cumulative_function_acc@10"] == pytest.approx(2 / 3, abs=1e-6)
    assert points[-1]["rolling_function_acc@10"] == 1.0


def test_cluster_bootstrap_weights_each_fix_once():
    cases = [
        {"case_id": "a", "underlying_fix_id": "one"},
        {"case_id": "b", "underlying_fix_id": "one"},
        {"case_id": "c", "underlying_fix_id": "two"},
    ]
    learned = {key: {"mrr": value} for key, value in {"a": 1, "b": 1, "c": 0}.items()}
    frozen = {key: {"mrr": value} for key, value in {"a": 0, "b": 0, "c": 1}.items()}
    gap = paired_cluster_gap(cases, learned, frozen, "mrr", 200, 7, 0.95)
    assert gap["mean"] == 0.0
    assert gap["underlying_fixes"] == 2


class FakeRanker:
    def __init__(self, fail_observe=False):
        self.edges = EdgeTable({("seed", "CALLS", "gold"): {"w": 1.0}})
        self.nodes = {}
        self.pending_nodes = {}
        self.concepts = {}
        self.symptoms = []
        self.memory = []
        self.fix_count = {}
        self._seen = 0
        self._mem_mat = None
        self._mem_dirty = False
        self.fail_observe = fail_observe

    def gold_concepts(self, _golds):
        return []

    def observe(self, issue):
        self.memory.append({"ticket": issue["ticket"]})
        if self.fail_observe:
            raise RuntimeError("flat observe injected")


class MutateThenFail:
    name = "injected_failure"

    def __init__(self):
        self.calls = 0

    def on_outcome(self, table, _episode):
        self.calls += 1
        table.ensure("concept:x", "SHORTCUT", "gold", learned=1)
        raise RuntimeError("injected")


def test_learning_failure_rolls_back_and_disables_all_later_updates():
    flat = FakeRanker()
    learned = FakeRanker()
    operator = MutateThenFail()
    prediction = Prediction(hits=[Hit("gold", "src/app.py", 1.0)], seeds=["seed"])
    row = issue(1, "a" * 40, 1, "query")
    enabled, status, applied, error = attempt_paired_update(
        flat, learned, row, prediction, [operator], True
    )
    assert (enabled, status, dict(applied), error) == (
        False,
        "failed_atomic_rollback",
        {},
        "RuntimeError",
    )
    assert ("concept:x", "SHORTCUT", "gold") not in learned.edges.edges
    assert flat.memory == []
    assert learned.memory == []
    assert operator.calls == 0


def test_flat_failure_rolls_back_both_memory_arms_and_disables_updates():
    flat = FakeRanker(fail_observe=True)
    learned = FakeRanker()
    operator = MutateThenFail()
    prediction = Prediction(hits=[Hit("gold", "src/app.py", 1.0)], seeds=["seed"])
    row = issue(1, "a" * 40, 1, "query")
    enabled, status, applied, error = attempt_paired_update(
        flat, learned, row, prediction, [operator], True
    )
    assert (enabled, status, dict(applied), error) == (
        False,
        "failed_atomic_rollback",
        {},
        "RuntimeError",
    )
    assert flat.memory == []
    assert learned.memory == []
    assert operator.calls == 0

    enabled, status, applied, error = attempt_paired_update(
        flat, learned, row, prediction, [operator], enabled
    )
    assert (enabled, status, dict(applied), error) == (
        False,
        "disabled_after_update_failure",
        {},
        None,
    )
    assert operator.calls == 0
