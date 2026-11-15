"""Bolt adapter for self-hosted HydraDB (openCypher over Neo4j Bolt).

Verified against ghcr.io/hydra-db/hydradb:0.4.0. The dialect is narrower
than hosted BYOG:

- Node identity is the integer `id` you assign. There is no CREATE INDEX.
- Edgeless nodes are written with UNWIND MERGE ... SET n:Label, n.prop = ...
  One label per batch. Labels first, then edges.
- The edge batch cannot carry properties. A second UNWIND MATCH SET writes
  w, hits, and misses. Re-running the edge batch does not duplicate edges
  and does not clear properties.
- Variable-length patterns need one type and an upper bound: [:CALLS*1..3].
  Cross-type walks use CALL algo.SSpaths with an inlined relTypes list.
  Procedure maps accept scalar parameters only, so lists are inlined.
- Bolt transactions (BEGIN/COMMIT) are rejected. Each session.run auto-commits.
- Batches are capped at 1024. This client chunks at 500.
- Reads can truncate. Fetchers page with SKIP/LIMIT and compare to count(*).
"""

from __future__ import annotations

from neo4j import GraphDatabase

from repocortex.hydradb.base import (
    LABELS,
    NODE_FIELDS,
    ExpandHit,
    ExpandResult,
    QueryResult,
    check_label,
    check_rel,
)

BATCH = 500
PAGE = 1000


def _plain(value):
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if hasattr(value, "to_native"):
        return value.to_native()
    return value


def _chunks(rows: list[dict], size: int):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def _node_row(node: dict, node_id: int) -> dict:
    row = {"id": int(node_id)}
    for key in NODE_FIELDS:
        value = node.get(key, "")
        if key in ("start", "end"):
            row[key] = int(value or 0)
        else:
            row[key] = "" if value is None else str(value)[:500]
    return row


def _path_nodes(path) -> tuple[str, list[str], int]:
    """Return (text, node uids along the walk, hop count) from an SSpaths list."""
    if not isinstance(path, list):
        return "", [], 0
    parts: list[str] = []
    uids: list[str] = []
    hops = 0
    for item in path:
        if isinstance(item, str):
            parts.append(item)
            hops += 1
            continue
        if isinstance(item, dict):
            uid = str(item.get("uid") or "")
            name = str(item.get("name") or uid)
            parts.append(name or uid)
            if uid:
                uids.append(uid)
    return " - ".join(parts), uids, hops


class BoltClient:
    def __init__(self, uri: str, user: str, password: str, database: str = "default"):
        self.database = database
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.uid_to_id: dict[str, int] = {}
        self.id_to_uid: dict[int, str] = {}
        self._next_id = 1
        self._ids_synced = False
        self._expand_cache: dict[tuple, list[ExpandHit]] = {}
        self.last_queries: list[dict] = []
        self.trace = False

    def close(self) -> None:
        self.driver.close()

    def verify(self) -> None:
        self.driver.verify_connectivity()

    def query(self, cypher: str, params: dict | None = None, timeout: float = 20.0, record: bool = True) -> QueryResult:
        if self.trace and record:
            self.last_queries.append({"cypher": cypher, "params": params or {}})
        with self.driver.session(database=self.database) as session:
            cursor = session.run(cypher, params or {}, timeout=timeout)
            rows = [_plain(record.data()) for record in cursor]
        return QueryResult.from_rows(rows)

    def ping(self) -> dict:
        """Cheap live check. Does not load the graph."""
        result = self.query("MATCH (n:Repo) RETURN n.uid AS uid LIMIT 1", record=False)
        row = result.rows[0] if result.rows else {}
        functions = self.query("MATCH (n:Function) RETURN count(*) AS n", record=False)
        count = int(functions.rows[0]["n"]) if functions.rows else 0
        return {"ok": bool(row and count), "repo": row.get("uid") or "", "functions": count}

    def resolve_uid(self, uid: str) -> int | None:
        """Look up the integer id for a uid, including nodes created in another process."""
        if not uid:
            return None
        existing = self.uid_to_id.get(uid)
        if existing is not None:
            return existing
        result = self.query("MATCH (n {uid: $uid}) RETURN n.id AS id LIMIT 1", {"uid": uid})
        if not result.rows or result.rows[0].get("id") is None:
            return None
        node_id = int(result.rows[0]["id"])
        self.remember(uid, node_id)
        return node_id

    def structural_edges(self, seeds: list[str]) -> list[tuple[tuple[str, str, str], float]]:
        """Read bounded one-hop edges used by live structural scoring."""
        found = []
        for rel in ("CALLS", "CO_CHANGED", "TESTED_BY", "DEFINES"):
            result = self.query(
                f"MATCH (a:Function)-[r:{rel}]->(b:Function) "
                "WHERE a.uid IN $seeds OR b.uid IN $seeds "
                "RETURN a.uid AS src, b.uid AS dst, r.w AS w ORDER BY a.uid, b.uid LIMIT 1000",
                {"seeds": seeds},
            )
            if self.trace:
                self.last_queries[-1]["rows"] = len(result.rows)
                self.last_queries[-1]["limit_reached"] = len(result.rows) == 1000
            if len(result.rows) == 1000:
                raise RuntimeError("structural traversal reached its limit; refusing partial ranking")
            for row in result.rows:
                found.append(((row["src"], rel, row["dst"]), float(row.get("w") or 1.0)))
        return found

    def _exec(self, cypher: str, params: dict | None = None) -> None:
        self.query(cypher, params, timeout=60.0)

    def remember(self, uid: str, node_id: int) -> None:
        self.uid_to_id[uid] = node_id
        self.id_to_uid[node_id] = uid
        if node_id >= self._next_id:
            self._next_id = node_id + 1

    def _assign(self, uid: str) -> int:
        existing = self.uid_to_id.get(uid)
        if existing is not None:
            return existing
        if not self._ids_synced:
            # Never reuse an id that already belongs to a node we have not fetched.
            self._ids_synced = True
            try:
                peak = None
                for label in LABELS:
                    result = self.query(
                        f"MATCH (n:{label}) RETURN n.id AS id ORDER BY n.id DESC LIMIT 1"
                    )
                    if result.rows and result.rows[0].get("id") is not None:
                        found = int(result.rows[0]["id"])
                        peak = found if peak is None else max(peak, found)
                if peak is not None:
                    self._next_id = max(self._next_id, peak + 1)
            except Exception:
                pass
        node_id = self._next_id
        self._next_id += 1
        self.remember(uid, node_id)
        return node_id

    def delete_ids(self, ids: list[int]) -> None:
        rows = [{"id": int(i)} for i in ids]
        for chunk in _chunks(rows, BATCH):
            self._exec(
                "UNWIND $rows AS row MATCH (n {id: row.id}) DETACH DELETE n",
                {"rows": chunk},
            )
        for node_id in ids:
            uid = self.id_to_uid.pop(int(node_id), None)
            if uid is not None:
                self.uid_to_id.pop(uid, None)

    def upsert_nodes(self, label: str, nodes: list[dict]) -> int:
        label = check_label(label)
        rows = []
        for node in nodes:
            uid = str(node["uid"])
            rows.append(_node_row(node, self._assign(uid)))
        cypher = (
            "UNWIND $rows AS row MERGE (n {id: row.id}) "
            f"SET n:{label}, n.uid = row.uid, n.name = row.name, n.file = row.file, "
            "n.qualname = row.qualname, n.signature = row.signature, n.doc = row.doc, "
            "n.start = row.start, n.end = row.end, n.kind = row.kind"
        )
        written = 0
        for chunk in _chunks(rows, BATCH):
            self._exec(cypher, {"rows": chunk})
            written += len(chunk)
        self._expand_cache.clear()
        return written

    def upsert_edges(self, rel: str, edges: list[dict]) -> int:
        rel = check_rel(rel)
        prepared = []
        for edge in edges:
            src = self.uid_to_id.get(str(edge["src"]))
            dst = self.uid_to_id.get(str(edge["dst"]))
            if src is None or dst is None or src == dst:
                continue
            prepared.append(
                {
                    "src": src,
                    "dst": dst,
                    "w": float(edge.get("w", 1.0)),
                    "hits": int(edge.get("hits", 0)),
                    "misses": int(edge.get("misses", 0)),
                    "count": int(edge.get("count", 1)),
                }
            )
        create = (
            "UNWIND $rows AS row "
            f"CREATE (a {{id: row.src}})-[:{rel}]->(b {{id: row.dst}})"
        )
        settle = (
            "UNWIND $rows AS row "
            f"MATCH (a {{id: row.src}})-[r:{rel}]->(b {{id: row.dst}}) "
            "SET r.w = row.w, r.hits = row.hits, r.misses = row.misses, r.count = row.count"
        )
        written = 0
        for chunk in _chunks(prepared, BATCH):
            self._exec(create, {"rows": chunk})
            self._exec(settle, {"rows": chunk})
            written += len(chunk)
        self._expand_cache.clear()
        return written

    def update_edge_weights(self, rel: str, edges: list[dict]) -> int:
        rel = check_rel(rel)
        rows = []
        for edge in edges:
            src = self.uid_to_id.get(str(edge["src"]))
            dst = self.uid_to_id.get(str(edge["dst"]))
            if src is None or dst is None:
                continue
            rows.append(
                {
                    "src": src,
                    "dst": dst,
                    "w": float(edge["w"]),
                    "hits": int(edge["hits"]),
                    "misses": int(edge["misses"]),
                }
            )
        cypher = (
            "UNWIND $rows AS row "
            f"MATCH (a {{id: row.src}})-[r:{rel}]->(b {{id: row.dst}}) "
            "SET r.w = row.w, r.hits = row.hits, r.misses = row.misses"
        )
        written = 0
        for chunk in _chunks(rows, BATCH):
            self._exec(cypher, {"rows": chunk})
            written += len(chunk)
        return written

    def count_label(self, label: str) -> int:
        label = check_label(label)
        result = self.query(f"MATCH (n:{label}) RETURN count(*) AS n")
        if not result.rows:
            return 0
        return int(result.rows[0]["n"])

    def count_rel(self, rel: str) -> int:
        rel = check_rel(rel)
        result = self.query(f"MATCH (a)-[r:{rel}]->(b) RETURN count(*) AS n")
        if not result.rows:
            return 0
        return int(result.rows[0]["n"])

    def fetch_nodes(self, label: str) -> tuple[list[dict], bool]:
        label = check_label(label)
        total = self.count_label(label)
        rows: list[dict] = []
        skip = 0
        while skip < total:
            page = self.query(
                f"MATCH (n:{label}) RETURN n.id AS id, n.uid AS uid, n.name AS name, "
                "n.file AS file, n.qualname AS qualname, n.signature AS signature, "
                "n.doc AS doc, n.kind AS kind, n.start AS start, n.end AS end "
                "ORDER BY n.id SKIP $skip LIMIT $limit",
                {"skip": skip, "limit": PAGE},
            )
            if not page.rows:
                break
            for row in page.rows:
                if row.get("uid"):
                    self.remember(str(row["uid"]), int(row["id"]))
                rows.append(row)
            skip += len(page.rows)
            if len(page.rows) < PAGE:
                break
        return rows, len(rows) < total

    def fetch_edges(self, rel: str) -> tuple[list[dict], bool]:
        rel = check_rel(rel)
        total = self.count_rel(rel)
        rows: list[dict] = []
        skip = 0
        while skip < total:
            page = self.query(
                f"MATCH (a)-[r:{rel}]->(b) "
                "RETURN a.uid AS src, b.uid AS dst, r.w AS w, r.hits AS hits, "
                "r.misses AS misses, r.count AS count "
                "ORDER BY a.uid, b.uid SKIP $skip LIMIT $limit",
                {"skip": skip, "limit": PAGE},
            )
            if not page.rows:
                break
            rows.extend(page.rows)
            skip += len(page.rows)
            if len(page.rows) < PAGE:
                break
        clean = [r for r in rows if r.get("src") and r.get("dst")]
        return clean, len(rows) < total

    def expand(self, seed_uids: list[str], hops: int = 2, limit: int = 400) -> ExpandResult:
        hops = max(1, min(int(hops), 3))
        hits: list[ExpandHit] = []
        seen: set[str] = set()
        truncated = False
        queries = 0
        rel_list = "'CALLS', 'DEFINES', 'CONTAINS', 'IMPORTS', 'INHERITS', 'TESTED_BY', 'CO_CHANGED', 'MENTIONS', 'RAISES'"
        for uid in seed_uids:
            if len(hits) >= limit:
                truncated = True
                break
            node_id = self.resolve_uid(uid)
            if node_id is None:
                continue
            cache_key = (uid, hops)
            cached = self._expand_cache.get(cache_key)
            if cached is None:
                cached = []
                queries += 1
                ss = (
                    "CALL algo.SSpaths({sourceNode: %d, relTypes: [%s], "
                    "relDirection: 'both', maxLen: %d, pathCount: 40}) "
                    "YIELD path RETURN path" % (node_id, rel_list, hops)
                )
                try:
                    result = self.query(ss, timeout=15.0)
                except Exception:
                    result = QueryResult.from_rows([])
                    truncated = True
                if len(result.rows) >= 40:
                    truncated = True
                for row in result.rows:
                    text, found, nhops = _path_nodes(row.get("path"))
                    for target in found:
                        if target != uid:
                            cached.append(ExpandHit(uid=target, path=text, hops=nhops))
                for rel in ("CALLS", "CO_CHANGED"):
                    queries += 1
                    vq = (
                        "MATCH (s {id: $id})-[:%s*1..%d]->(f:Function) "
                        "WHERE f.id <> $id RETURN f.uid AS uid LIMIT 80" % (rel, hops)
                    )
                    try:
                        grew = self.query(vq, {"id": node_id}, timeout=15.0)
                    except Exception:
                        truncated = True
                        continue
                    if len(grew.rows) >= 80:
                        truncated = True
                    for row in grew.rows:
                        target = row.get("uid")
                        if target and target != uid:
                            cached.append(
                                ExpandHit(
                                    uid=str(target),
                                    path=f"{uid} -{rel}*1..{hops}-> {target}",
                                    hops=hops,
                                )
                            )
                self._expand_cache[cache_key] = cached
            for hit in cached:
                if hit.uid in seen:
                    continue
                seen.add(hit.uid)
                hits.append(hit)
                if len(hits) >= limit:
                    truncated = True
                    break
        return ExpandResult(hits=hits, truncated=truncated, queries=queries)
