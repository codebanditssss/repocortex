import assert from "node:assert/strict";
import test from "node:test";
import { estimatedTokens, isBackendStatus, isLocateResult, repairBrief, shortLiveName, receiptRelation, sourceUrl } from "../lib/live.ts";

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

test("source links point to exact lines in the frozen Django snapshot", () => {
  const hit = valid.hits[0];
  const snapshot = "f24f38c6b2825f15628c07bf2892f1664eed9361";
  assert.equal(sourceUrl(hit, snapshot), `https://github.com/django/django/blob/${snapshot}/query.py#L2`);
  assert.equal(sourceUrl({ ...hit, file: "django/db/query compiler.py" }, snapshot), `https://github.com/django/django/blob/${snapshot}/django/db/query%20compiler.py#L2`);
  assert.equal(sourceUrl({ ...hit, file: "../secret", line: 2 }, snapshot), null);
  assert.equal(sourceUrl({ ...hit, line: 0 }, snapshot), null);
  assert.equal(sourceUrl(hit, "main"), null);
});

test("repair briefs contain bounded candidates, source evidence, and graph receipts", () => {
  const snapshot = "f24f38c6b2825f15628c07bf2892f1664eed9361";
  const result = {
    ...valid,
    hits: Array.from({ length: 7 }, (_, index) => ({ ...valid.hits[0], rank: index + 1, uid: `fn:${index}`, qualname: `Query.candidate_${index}`, score: .9 - index / 100 })),
    queries: [{ ...valid.queries[0], cypher: "MATCH (a)-[r:CALLS]->(b) RETURN b", rows: 12 }],
  };
  const brief = repairBrief("  Query compilation fails  ", result, snapshot);
  assert.match(brief, /# RepoCortex repair brief/);
  assert.match(brief, /Query compilation fails/);
  assert.match(brief, /Query\.candidate_0/);
  assert.match(brief, /github\.com\/django\/django\/blob\/f24f38c/);
  assert.match(brief, /CALLS \(1\)/);
  assert.match(brief, /Database queries: 1; rows returned: 12/);
  assert.match(brief, /Representative Cypher receipts:[\s\S]*MATCH \(a\)-\[r:CALLS\]->\(b\) RETURN b/);
  assert.doesNotMatch(brief, /Query\.candidate_5/);
  assert.equal(estimatedTokens("12345"), 2);
});
