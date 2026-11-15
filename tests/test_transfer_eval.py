"""The transfer miner must never turn commit or PR prose into an issue report."""
import json
from types import SimpleNamespace

from scripts import eval_transfer


def test_miner_requires_real_pre_fix_issue_and_deduplicates(monkeypatch, tmp_path):
    graph = SimpleNamespace(nodes={"fn:src/flask/app.py:run": SimpleNamespace(label="Function")})
    monkeypatch.setattr(eval_transfer, "build_graph", lambda _: graph)
    monkeypatch.setattr(eval_transfer, "iter_sources", lambda *_: [])
    monkeypatch.setattr(eval_transfer, "snapshot_sha", lambda _: "snapshot")
    monkeypatch.setattr(eval_transfer, "gold_functions_for_commit", lambda *_: list(graph.nodes))
    def issue(number, body="user report", created="2020-01-01T00:00:00Z"):
        return {"number": number, "title": "failure", "body": body, "createdAt": created, "url": f"https://github.com/pallets/flask/issues/{number}"}
    refs = {"p3": {"closingIssuesReferences": {"nodes": [issue(5), issue(6, body=""), issue(7, created="2030-01-01T00:00:00Z")]}},
            "p2": {"closingIssuesReferences": {"nodes": [issue(5)]}},
            "p1": {"closingIssuesReferences": {"nodes": []}}}
    def command(*args):
        if args[0] == "git":
            return "c3\x1f1700000003\x1fcommit prose (#3)\nc2\x1f1700000002\x1fmore prose (#2)\nc1\x1f1700000001\x1fnot a report (#1)"
        return json.dumps({"data": {"repository": refs}})
    monkeypatch.setattr(eval_transfer, "command", command)
    dataset, _ = eval_transfer.mine(tmp_path, tmp_path, 10)
    assert len(dataset["issues"]) == 1
    assert dataset["issues"][0]["description"] == "user report"
    assert dataset["issues"][0]["text_source"] == "github_issue"
    assert dataset["selection_counts"] == {"unique_pr_references_scanned": 3, "linked_issue_references": 4, "empty_issue_body": 1, "issue_created_after_fix": 1, "duplicate_issue_references": 1, "eligible_prs_without_closing_issue": 1, "eligible_pr_commits": 3, "retained_unique_issues": 1}
