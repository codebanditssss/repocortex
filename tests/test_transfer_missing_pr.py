"""A commit's (#N) suffix may name an issue, not a pull request."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from scripts import eval_transfer


def partial():
    return {
        "data": {"repository": {
            "p1": None,
            "p2": {"closingIssuesReferences": {"nodes": []}},
        }},
        "errors": [{"type": "NOT_FOUND", "path": ["repository", "p1"],
                    "message": "Could not resolve to a PullRequest with the number of 1."}],
    }


def test_partial_nonzero_response_keeps_valid_prs(monkeypatch):
    response = partial()
    def fail(*args):
        raise subprocess.CalledProcessError(1, args, output=json.dumps(response))
    monkeypatch.setattr(eval_transfer, "command", fail)
    assert eval_transfer.query_pull_requests("query", [1, 2]) == response
    assert eval_transfer.missing_pr_references(response, [1, 2]) == {1}


@pytest.mark.parametrize("error", [
    {"type": "RATE_LIMITED", "path": ["repository", "p1"], "message": "rate limited"},
    {"type": "FORBIDDEN", "path": ["repository", "p1"], "message": "denied"},
    {"type": "NOT_FOUND", "path": ["repository"], "message": "missing repository"},
    {"type": "NOT_FOUND", "path": ["repository", "p3"], "message": "Could not resolve to a PullRequest with the number of 3."},
    {"type": "NOT_FOUND", "path": ["repository", "p1"], "message": "unknown problem"},
])
def test_unknown_graphql_errors_are_not_swallowed(monkeypatch, error):
    response = partial()
    response["errors"].append(error)
    def fail(*args):
        raise subprocess.CalledProcessError(1, args, output=json.dumps(response))
    monkeypatch.setattr(eval_transfer, "command", fail)
    with pytest.raises(RuntimeError):
        eval_transfer.query_pull_requests("query", [1, 2])


@pytest.mark.parametrize("output", ["", "not json", "{}", '{"data":null}'])
def test_non_graphql_failures_remain_failures(monkeypatch, output):
    def fail(*args):
        raise subprocess.CalledProcessError(1, args, output=output)
    monkeypatch.setattr(eval_transfer, "command", fail)
    with pytest.raises(subprocess.CalledProcessError):
        eval_transfer.query_pull_requests("query", [1, 2])


def test_unexplained_null_pr_fails():
    response = partial()
    response.pop("errors")
    with pytest.raises(RuntimeError, match="omitted"):
        eval_transfer.missing_pr_references(response, [1, 2])


def test_miner_counts_missing_pr_and_does_not_replace_it(monkeypatch, tmp_path):
    graph = SimpleNamespace(nodes={"fn:src/flask/a.py:run": SimpleNamespace(label="Function")})
    monkeypatch.setattr(eval_transfer, "build_graph", lambda _: graph)
    monkeypatch.setattr(eval_transfer, "iter_sources", lambda *_: [])
    monkeypatch.setattr(eval_transfer, "snapshot_sha", lambda _: "snapshot")
    mapped = []
    def gold(repo, sha, *args):
        mapped.append(sha)
        return list(graph.nodes)
    monkeypatch.setattr(eval_transfer, "gold_functions_for_commit", gold)
    calls = []
    def command(*args):
        if args[0] == "git":
            return "c1\x1f1700000001\x1fchange (#1)\nc2\x1f1700000002\x1fchange (#2)\nc3\x1f1700000003\x1fchange (#3)"
        calls.append(args)
        raise subprocess.CalledProcessError(1, args, output=json.dumps(partial()))
    monkeypatch.setattr(eval_transfer, "command", command)
    first, _ = eval_transfer.mine(tmp_path, tmp_path, 2)
    assert mapped == ["c1", "c2"]
    assert first["selection_counts"]["missing_pull_request_references"] == 1
    assert first["selection_counts"]["eligible_prs_without_closing_issue"] == 1
    assert first["selection_counts"]["eligible_pr_commits"] == 2
    second, _ = eval_transfer.mine(tmp_path, tmp_path, 2)
    assert second == first
    assert len(calls) == 1  # Missing-reference evidence survives cache reads.
