import assert from "node:assert/strict";
import test from "node:test";
import { isBackendStatus, isLocateResult, shortLiveName, receiptRelation } from "../lib/live.ts";

const valid = { hits: [{ rank: 1, uid: "fn:query", file: "query.py", qualname: "Query", line: 2, score: .4, path: "CALLS" }], backend: { mode: "live", connected: true }, source: "live", scoring: "live structural graph + cached learned memory", queries: [{ cypher: "MATCH (n) RETURN n", params: {}, rows: 12, limit_reached: false }] };
test("live contract accepts genuine live and cached results, including empty search", () => {
  assert.equal(isLocateResult(valid), true);
  assert.equal(isLocateResult({ ...valid, source: "replay", hits: [], queries: [], backend: { mode: "replay", connected: false } }), true);
});
test("live contract rejects missing provenance and malformed rankings", () => {
  for (const value of [null, {}, { ...valid, queries: undefined }, { ...valid, source: "mock" }, { ...valid, hits: [{ ...valid.hits[0], score: NaN }] }, { ...valid, backend: { connected: "true" } }, { ...valid, queries: [{ cypher: 9, params: {}, rows: 12, limit_reached: false }] }]) assert.equal(isLocateResult(value), false);
  assert.equal(isBackendStatus({ mode: "unavailable", connected: false }), true);
  assert.equal(isBackendStatus({ mode: "live", connected: "false" }), false);
});

test("receipt counts and truncation are required; names stay concise", () => {
  assert.equal(isLocateResult({ ...valid, queries: [{ ...valid.queries[0], rows: -1 }] }), false);
  assert.equal(isLocateResult({ ...valid, queries: [{ ...valid.queries[0], limit_reached: undefined }] }), false);
  assert.equal(shortLiveName({ ...valid.hits[0], qualname: "django.db.models.query.QuerySet.union" }), "QuerySet.union");
  assert.equal(receiptRelation({ ...valid.queries[0], cypher: "MATCH (a)-[r:CALLS]->(b) RETURN b" }), "CALLS");
});
