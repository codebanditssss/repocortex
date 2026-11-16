"""Hosted HydraDB BYOG adapter.

POST https://api.hydradb.com/byog/query
body: {database, collection, query, params}
headers: Authorization: Bearer <key>, API-Version: 2

Hosted openCypher is wider than the OSS engine (undirected and untyped
variable-length walks, MERGE ... SET, indexes). This adapter uses that
dialect and keeps the same Python methods as BoltClient.

Rows can truncate without an error. Reads use LIMIT and a separate count,
then page with SKIP until the count is covered or a cap is hit.
"""

from __future__ import annotations

import httpx

from repocortex.graph.weights import edge_weight
from repocortex.hydradb.base import (
    NODE_FIELDS,
    ExpandHit,
    ExpandResult,
    QueryResult,
    check_label,
    check_rel,
)

BATCH = 200
PAGE = 500


class HostedError(RuntimeError):
    pass


class HostedClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        database: str,
        collection: str,
        timeout: float = 30.0,
    ):
        if not api_key:
            raise HostedError("HYDRADB_API_KEY is empty; hosted BYOG needs a key")
        self.base_url = base_url.rstrip("/")
        self.database = database
        self.collection = collection
        self.timeout = timeout
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "API-Version": "2",
                "Content-Type": "application/json",
            },
        )
        self._indexes: set[str] = set()

    def close(self) -> None:
        self._client.close()

    def verify(self) -> None:
        response = self._client.get(f"{self.base_url}/byog/collections", params={"database": self.database})
        if response.status_code == 404:
            created = self._client.post(
                f"{self.base_url}/byog/databases",
                json={"database": self.database},
            )
            if created.status_code not in (200, 201, 409):
                raise HostedError(f"create database failed: {created.status_code} {created.text[:300]}")
            return
        if response.status_code >= 300:
            raise HostedError(f"hosted check failed: {response.status_code} {response.text[:300]}")

    def query(self, cypher: str, params: dict | None = None, timeout: float | None = None) -> QueryResult:
        payload = {
            "database": self.database,
            "collection": self.collection,
            "query": cypher,
            "params": params or {},
        }
        response = self._client.post(
            f"{self.base_url}/byog/query",
            json=payload,
            timeout=timeout or self.timeout,
        )
        if response.status_code >= 300:
            raise HostedError(f"byog query failed: {response.status_code} {response.text[:400]}")
        body = response.json()
        if not body.get("success", False) or body.get("error"):
            raise HostedError(f"byog query error: {body.get('error')}")
        data = body.get("data") or []
        if isinstance(data, dict):
            data = [data]
        meta = body.get("meta") or {}
        rows = list(data)
        return QueryResult(
            rows=rows,
            row_count=len(rows),
            truncated=False,
            reported_total=None if meta.get("request_id") is None else None,
        )

    def _count(self, cypher: str, params: dict | None = None) -> int:
        result = self.query(cypher, params)
        if not result.rows:
            return 0
        row = result.rows[0]
        for key in ("n", "count", "total"):
            if key in row:
                return int(row[key])
        return int(next(iter(row.values())))

    def _ensure_index(self, label: str) -> None:
        if label in self._indexes:
            return
        try:
            self.query(f"CREATE INDEX FOR (n:{label}) ON (n.uid)")
        except HostedError:
            pass
        self._indexes.add(label)

    def delete_ids(self, ids: list[int]) -> None:
        # Hosted nodes are keyed by uid. `ids` here may be uids passed as strings
        # through a parallel call path; integer leftovers are ignored.
        uids = [str(i) for i in ids if not isinstance(i, int)]
        if not uids:
            return
        self.query(
            "UNWIND $rows AS uid MATCH (n {uid: uid}) DETACH DELETE n",
            {"rows": uids},
        )

    def delete_uids(self, uids: list[str]) -> None:
        for i in range(0, len(uids), BATCH):
            self.query(
                "UNWIND $rows AS uid MATCH (n {uid: uid}) DETACH DELETE n",
                {"rows": uids[i : i + BATCH]},
            )

    def upsert_nodes(self, label: str, nodes: list[dict]) -> int:
        label = check_label(label)
        self._ensure_index(label)
        rows = []
        for node in nodes:
            row = {"uid": str(node["uid"])}
            for key in NODE_FIELDS:
                if key == "uid":
                    continue
                value = node.get(key, "")
                if key in ("start", "end"):
                    row[key] = int(value or 0)
                else:
                    row[key] = "" if value is None else str(value)[:500]
            rows.append(row)
        cypher = (
            f"UNWIND $rows AS row MERGE (n:{label} {{uid: row.uid}}) "
            "SET n.name = row.name, n.file = row.file, n.qualname = row.qualname, "
            "n.signature = row.signature, n.doc = row.doc, n.start = row.start, "
            "n.end = row.end, n.kind = row.kind "
            "RETURN count(n) AS n"
        )
        written = 0
        for i in range(0, len(rows), BATCH):
            result = self.query(cypher, {"rows": rows[i : i + BATCH]})
            written += int(result.rows[0]["n"]) if result.rows else len(rows[i : i + BATCH])
        return written

    def upsert_edges(self, rel: str, edges: list[dict]) -> int:
        rel = check_rel(rel)
        rows = [
            {
                "src": str(edge["src"]),
                "dst": str(edge["dst"]),
                "w": edge_weight(edge),
                "hits": int(edge.get("hits", 0)),
                "misses": int(edge.get("misses", 0)),
                "count": int(edge.get("count", 1)),
            }
            for edge in edges
            if edge.get("src") and edge.get("dst") and edge["src"] != edge["dst"]
        ]
        cypher = (
            "UNWIND $rows AS row "
            "MATCH (a {uid: row.src}), (b {uid: row.dst}) "
            f"MERGE (a)-[r:{rel}]->(b) "
            "SET r.w = row.w, r.hits = row.hits, r.misses = row.misses, r.count = row.count "
            "RETURN count(r) AS n"
        )
        written = 0
        for i in range(0, len(rows), BATCH):
            result = self.query(cypher, {"rows": rows[i : i + BATCH]})
            written += int(result.rows[0]["n"]) if result.rows else 0
        return written

    def update_edge_weights(self, rel: str, edges: list[dict]) -> int:
        rel = check_rel(rel)
        rows = [
            {
                "src": str(edge["src"]),
                "dst": str(edge["dst"]),
                "w": float(edge["w"]),
                "hits": int(edge["hits"]),
                "misses": int(edge["misses"]),
            }
            for edge in edges
        ]
        cypher = (
            "UNWIND $rows AS row "
            "MATCH (a {uid: row.src})-[r:%s]->(b {uid: row.dst}) "
            "SET r.w = row.w, r.hits = row.hits, r.misses = row.misses "
            "RETURN count(r) AS n" % rel
        )
        written = 0
        for i in range(0, len(rows), BATCH):
            result = self.query(cypher, {"rows": rows[i : i + BATCH]})
            written += int(result.rows[0]["n"]) if result.rows else 0
        return written

    def count_label(self, label: str) -> int:
        label = check_label(label)
        return self._count(f"MATCH (n:{label}) RETURN count(n) AS n")

    def count_rel(self, rel: str) -> int:
        rel = check_rel(rel)
        return self._count(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS n")

    def _page(self, cypher: str) -> tuple[list[dict], bool]:
        total_query = cypher
        # Caller passes a query that already returns rows. Count is separate.
        rows: list[dict] = []
        skip = 0
        reported = None
        while True:
            page = self.query(f"{cypher} SKIP $skip LIMIT $limit", {"skip": skip, "limit": PAGE})
            rows.extend(page.rows)
            if len(page.rows) < PAGE:
                break
            skip += PAGE
            if skip > 200_000:
                break
        return rows, reported is not None and len(rows) < reported

    def fetch_nodes(self, label: str) -> tuple[list[dict], bool]:
        label = check_label(label)
        total = self.count_label(label)
        rows, _ = self._page(
            f"MATCH (n:{label}) RETURN n.uid AS uid, n.name AS name, n.file AS file, "
            "n.qualname AS qualname, n.signature AS signature, n.doc AS doc, n.kind AS kind "
            "ORDER BY n.uid"
        )
        return rows, len(rows) < total

    def fetch_edges(self, rel: str) -> tuple[list[dict], bool]:
        rel = check_rel(rel)
        total = self.count_rel(rel)
        rows, _ = self._page(
            f"MATCH (a)-[r:{rel}]->(b) "
            "RETURN a.uid AS src, b.uid AS dst, r.w AS w, r.hits AS hits, "
            "r.misses AS misses, r.count AS count ORDER BY a.uid, b.uid"
        )
        clean = [r for r in rows if r.get("src") and r.get("dst")]
        return clean, len(clean) < total

    def expand(self, seed_uids: list[str], hops: int = 2, limit: int = 400) -> ExpandResult:
        hops = max(1, min(int(hops), 3))
        if not seed_uids:
            return ExpandResult()
        count = self._count(
            "MATCH (s) WHERE s.uid IN $seeds "
            f"MATCH (s)-[*1..{hops}]-(f:Function) "
            "RETURN count(f) AS n",
            {"seeds": seed_uids},
        )
        result = self.query(
            "MATCH (s) WHERE s.uid IN $seeds "
            f"MATCH (s)-[*1..{hops}]-(f:Function) "
            "WHERE f.uid <> s.uid "
            "RETURN DISTINCT f.uid AS uid LIMIT $limit",
            {"seeds": seed_uids, "limit": limit},
        )
        hits = [
            ExpandHit(uid=str(row["uid"]), path=f"seed -[*1..{hops}]- {row['uid']}", hops=hops)
            for row in result.rows
            if row.get("uid")
        ]
        return ExpandResult(hits=hits, truncated=count > len(hits), queries=2)

    def send_feedback(
        self,
        request_id: str,
        *,
        ground_truth: dict | None = None,
        feedback: str = "",
        rating: str = "neutral",
    ) -> None:
        """Fire-and-forget POST /feedback. Failures are swallowed."""
        if not request_id:
            return
        payload: dict = {
            "request_id": request_id,
            "source": "agent",
            "rating": rating,
            "database": self.database,
            "collection": self.collection,
        }
        if ground_truth:
            payload["ground_truth"] = ground_truth
        if feedback:
            payload["feedback"] = feedback[:8000]
        try:
            self._client.post(f"{self.base_url}/feedback", json=payload)
        except Exception:
            return
