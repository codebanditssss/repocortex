import copy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from scripts.register_track1_eval import (
    audit_dataset,
    build_registration,
    canonical_json,
    default_evaluator_paths,
    immutable_case_id,
    source_manifest,
    with_registration_digest,
)
from scripts.summarize_track1_eval import paired_cluster_gap, summarize


def issue(ticket, commit, time, split, text, gold="func:a.py:a"):
    return {
        "ticket": ticket,
        "commit": commit,
        "time": time,
        "split": split,
        "summary": text,
        "description": "details " + text,
        "gold_functions": [gold],
        "gold_files": ["a.py"],
    }


def dataset():
    return {
        "repository": "owner/repo",
        "snapshot": "a" * 40,
        "scope": ["src"],
        "issues": [
            issue(1, "1" * 40, 1, "train", "socket closes too soon"),
            issue(2, "2" * 40, 2, "train", "header parser drops commas"),
            issue(3, "3" * 40, 3, "test", "redirect strips credentials"),
            issue(4, "4" * 40, 4, "test", "timeout wraps wrong exception"),
        ],
    }


def registration():
    audited = audit_dataset(dataset(), 0.35)
    payload = {
        "protocol_version": "track1-localization-v1",
        "uncertainty": {"resamples": 200, "seed": 9},
        "execution_contract": {"failure_after_scoring_starts": "failures score zero"},
        "primary_metric": "function_acc@10",
        "repositories": [audited],
    }
    payload["registration_sha256"] = hashlib.sha256(canonical_json(payload)).hexdigest()
    return payload


def test_registration_produces_stable_case_ids_and_fix_groups():
    audited = audit_dataset(dataset(), 0.35)
    assert audited["holdout_rows"] == 2
    assert audited["underlying_holdout_fixes"] == 2
    row = dataset()["issues"][2]
    assert audited["cases"][0]["case_id"] == immutable_case_id("owner/repo", "a" * 40, row)
    assert audited["cases"][0]["underlying_fix_id"] == "owner/repo@" + "3" * 40


def test_registration_rejects_near_duplicate_queries():
    value = dataset()
    value["issues"][2]["summary"] = value["issues"][0]["summary"]
    value["issues"][2]["description"] = value["issues"][0]["description"] + " one extra word"
    with pytest.raises(ValueError, match="near-duplicate"):
        audit_dataset(value, 0.35)


def test_cluster_gap_weights_each_underlying_fix_once():
    cases = [
        {"case_id": "a", "underlying_fix_id": "fix-1"},
        {"case_id": "b", "underlying_fix_id": "fix-1"},
        {"case_id": "c", "underlying_fix_id": "fix-2"},
    ]
    learned = {key: {"function_acc@10": value} for key, value in {"a": 1, "b": 1, "c": 0}.items()}
    frozen = {key: {"function_acc@10": value} for key, value in {"a": 0, "b": 0, "c": 1}.items()}
    gap = paired_cluster_gap(cases, learned, frozen, "function_acc@10", 200, 3)
    assert gap["mean"] == 0.0
    assert gap["cases"] == 3
    assert gap["underlying_fixes"] == 2


def test_failures_stay_in_denominator_as_zero():
    spec = registration()
    cases = spec["repositories"][0]["cases"]
    arms = {}
    for arm in ("text_only", "frozen_graph", "learned_graph"):
        arms[arm] = [
            {"case_id": cases[0]["case_id"], "status": "completed", "function_acc@10": 1, "mrr": 1},
            {"case_id": cases[1]["case_id"], "status": "timeout"},
        ]
    scores = {
        "registration_sha256": spec["registration_sha256"],
        "repositories": [{"repository": "owner/repo", "arms": arms}],
    }
    result = summarize(spec, scores)["repositories"][0]
    assert result["arms"]["learned_graph"]["cases"] == 2
    assert result["arms"]["learned_graph"]["function_acc@10"] == 0.5
    assert result["arms"]["learned_graph"]["failures"] == {"timeout": 1}


def test_score_file_must_have_every_registered_case_in_every_arm():
    spec = registration()
    case = spec["repositories"][0]["cases"][0]
    one = {"case_id": case["case_id"], "status": "completed", "function_acc@10": 1, "mrr": 1}
    scores = {
        "registration_sha256": spec["registration_sha256"],
        "repositories": [{
            "repository": "owner/repo",
            "arms": {arm: [copy.deepcopy(one)] for arm in ("text_only", "frozen_graph", "learned_graph")},
        }],
    }
    with pytest.raises(ValueError, match="one outcome is required per case"):
        summarize(spec, scores)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_source_manifest_locks_ranker_source_and_git_state(tmp_path):
    root = tmp_path / "repo"
    hybrid = root / "repocortex" / "retrieve" / "hybrid.py"
    evaluator = root / "scripts" / "eval_repository_ablation.py"
    hybrid.parent.mkdir(parents=True)
    evaluator.parent.mkdir(parents=True)
    hybrid.write_text("VALUE = 1\n")
    evaluator.write_text("# evaluator\n")
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-qm", "freeze")

    paths = default_evaluator_paths(root)
    assert [path.relative_to(root).as_posix() for path in paths] == [
        "repocortex/retrieve/hybrid.py",
        "scripts/eval_repository_ablation.py",
    ]
    first, first_digest, first_git = source_manifest(root, paths)
    assert first_git["tracked_source_changes"] == []
    assert first[0]["path"] == "repocortex/retrieve/hybrid.py"

    hybrid.write_text("VALUE = 2\n")
    second, second_digest, second_git = source_manifest(root, paths)
    assert first_digest != second_digest
    assert second_git["head"] == first_git["head"]
    assert second_git["tracked_source_changes"] == ["M repocortex/retrieve/hybrid.py"]


def test_ranker_source_change_changes_registration_digest(tmp_path):
    root = tmp_path / "repo"
    hybrid = root / "repocortex" / "retrieve" / "hybrid.py"
    evaluator = root / "scripts" / "eval_repository_ablation.py"
    data_path = root / "dataset.json"
    hybrid.parent.mkdir(parents=True)
    evaluator.parent.mkdir(parents=True)
    hybrid.write_text("VALUE = 1\n")
    evaluator.write_text("# evaluator\n")
    data_path.write_text(json.dumps(dataset()))
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-qm", "freeze")
    paths = default_evaluator_paths(root)

    first = build_registration([data_path], paths, 0.35, root)
    first["registered_at"] = "fixed"
    first_digest = with_registration_digest(first)["registration_sha256"]
    hybrid.write_text("VALUE = 2\n")
    second = build_registration([data_path], paths, 0.35, root)
    second["registered_at"] = "fixed"
    second_digest = with_registration_digest(second)["registration_sha256"]
    assert first_digest != second_digest


def test_source_manifest_rejects_duplicate_missing_and_non_file(tmp_path):
    root = tmp_path / "repo"
    source = root / "source.py"
    directory = root / "folder"
    source.parent.mkdir(parents=True)
    source.write_text("pass\n")
    directory.mkdir()
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-qm", "freeze")
    with pytest.raises(ValueError, match="duplicate"):
        source_manifest(root, [source, source])
    with pytest.raises(ValueError, match="does not exist"):
        source_manifest(root, [root / "missing.py"])
    with pytest.raises(ValueError, match="not a file"):
        source_manifest(root, [directory])
