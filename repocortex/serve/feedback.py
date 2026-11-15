"""Single-writer, namespaced feedback journal in HydraDB.

The journal is durable; scoring state is rebuilt from it atop the same base
snapshot. It does not change the benchmark's structural graph. Keep a namespace
bound to one corpus snapshot and one writer. This is not an accuracy benchmark.
"""
from __future__ import annotations

import hashlib
import json
import re
import time


def feedback_digest(report: str, diff: str) -> str:
    return hashlib.sha256(json.dumps([report, diff], separators=(",", ":")).encode()).hexdigest()


def feedback_ticket(report: str, diff: str) -> int:
    # 60 bits, separated from mined ticket ids; the old million-id range collided.
    return (1 << 60) + int(feedback_digest(report, diff)[:15], 16)


class FeedbackJournal:
    def __init__(self, client, namespace: str, fingerprint: str = ""):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", namespace):
            raise ValueError("feedback namespace must be 1–100 letters, digits, dots, underscores or hyphens")
        self.client = client
        self.namespace = namespace
        self.fingerprint = fingerprint

    def events(self) -> list[dict]:
        rows = []
        while True:
            page = self.client.query(
                "MATCH (n:FeedbackRecord) WHERE n.namespace = $namespace "
                "RETURN n.payload AS payload ORDER BY n.sequence, n.uid SKIP $skip LIMIT 500",
                {"namespace": self.namespace, "skip": len(rows)},
            ).rows
            rows.extend(page)
            if len(page) < 500:
                break
        events = [json.loads(row["payload"]) for row in rows]
        for event in events:
            if event.get("base") != self.fingerprint:
                raise ValueError("feedback journal belongs to a different base snapshot")
            if event.get("digest") != feedback_digest(event["report"], event["diff"]):
                raise ValueError("feedback journal integrity check failed")
        return events

    def append(self, report: str, diff: str, golds: list[str]) -> None:
        digest = feedback_digest(report, diff)
        uid = f"feedback:{self.namespace}:{digest}"
        # Reserve high positive ids, away from the corpus adapter's sequential ids.
        node_id = (1 << 60) + int(hashlib.sha256(uid.encode()).hexdigest()[:15], 16)
        existing = self.client.query(
            "MATCH (n {id: $id}) RETURN n.uid AS uid, n.payload AS payload LIMIT 1", {"id": node_id}
        ).rows
        event = {"base": self.fingerprint, "digest": digest, "report": report, "diff": diff, "golds": golds}
        payload = json.dumps(event, separators=(",", ":"))
        if existing:
            if existing[0]["uid"] != uid or existing[0]["payload"] != payload:
                raise ValueError("feedback journal identity conflict")
            return
        self.client.query(
            "UNWIND $rows AS row MERGE (n {id: row.id}) SET n:FeedbackRecord, n.uid = row.uid, "
            "n.namespace = row.namespace, n.sequence = row.sequence, n.payload = row.payload",
            {"rows": [{"id": node_id, "uid": uid, "namespace": self.namespace,
             "sequence": time.time_ns(), "payload": payload}]},
        )


def configure_feedback(ranker, namespace: str, operators=None) -> dict:
    """Replay the journal before serving, then enable durable future feedback.

    Requires a connected client. Fail closed on unavailable or invalid journal.
    Pass the same operators that subsequent writes use. No disk state is saved;
    the base snapshot must remain unchanged for deterministic reconstruction.
    """
    if ranker.client is None:
        raise RuntimeError("durable feedback requires a connected HydraDB client")
    # Bind the journal to the exact base used for learning, not merely its paths.
    base = hashlib.sha256()
    # Journal replay must use the same diff-label semantics as its writer.
    base.update(b"repocortex-feedback-changed-lines-v2\0")
    base.update(json.dumps(ranker.nodes, sort_keys=True, separators=(",", ":")).encode())
    for key, props in sorted(ranker.edges.edges.items()):
        base.update(json.dumps([key, props], sort_keys=True, separators=(",", ":")).encode())
    base.update(json.dumps([ranker.func_uids, list(ranker.matrix.shape), str(ranker.matrix.dtype)]).encode())
    base.update(ranker.matrix.tobytes())
    for item in ranker.memory:
        base.update(json.dumps([item["ticket"], item["golds"]], separators=(",", ":")).encode())
        base.update(item["vec"].tobytes())
    journal = FeedbackJournal(ranker.client, namespace, base.hexdigest())
    if operators is None:
        from repocortex.learn.compress import PathCompressor
        from repocortex.learn.replay import make_operators
        operators = make_operators(ranker, "full", lr=0.25, merger_every=40)
        for operator in operators:
            if isinstance(operator, PathCompressor):
                operator.hydrate(ranker.edges)
    from repocortex.serve.learn import learn_from_fix
    events = journal.events()
    client = ranker.client
    ranker.client = None
    try:
        for event in events:
            if any(gold not in ranker.uid_index for gold in event["golds"]):
                raise ValueError("feedback journal does not match this corpus")
            result = learn_from_fix(ranker, event["report"], event["diff"], operators=operators)
            if result.get("error") or set(result["learned"]) != set(event["golds"]):
                raise ValueError("feedback journal does not match this corpus")
    finally:
        ranker.client = client
    ranker.feedback_journal = journal
    ranker.feedback_operators = operators
    return {"storage": "hydradb feedback journal", "namespace": namespace, "replayed": len(events)}
