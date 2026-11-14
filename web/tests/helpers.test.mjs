import assert from "node:assert/strict";
import test from "node:test";
import { atkinson, bigGraph, makeGraph, rng } from "../lib/graph.ts";
import { chapterForPath, chapters } from "../lib/chapters.ts";
import { formatPercent } from "../lib/format.ts";
import * as loaders from "../lib/data.ts";

test("seeded graph helpers are repeatable and safe to import without a DOM", () => {
  const a = rng(99);
  const b = rng(99);
  for (let i = 0; i < 50; i++) {
    const value = a();
    assert.equal(value, b());
    assert.ok(value >= 0 && value < 1);
  }
  const first = bigGraph(99);
  assert.deepEqual(first, bigGraph(99));
  assert.notDeepEqual(first, bigGraph(100));
  assert.equal(first.nodes.length, 565);
  assert.ok(first.edges.every((edge) => first.nodes[edge.s] && first.nodes[edge.t]));
});

test("graph pins remain fixed through layout relaxation, including a zero-weight link", () => {
  const graph = makeGraph({
    seed: 7, iters: 3, cross: 0,
    pinned: [{ id: "anchor", x: .2, y: .3 }],
    clusters: [{ x: .4, y: .5, n: 6, spread: .1 }],
    links: [["anchor", "c0_0", 0, "CALLS"]],
  });
  assert.equal(graph.byId.anchor.x, .2);
  assert.equal(graph.byId.anchor.y, .3);
  assert.equal(graph.edges.find((edge) => edge.key).w, 0);
  assert.equal(graph.nodes.reduce((sum, node) => sum + node.deg, 0), graph.edges.length * 2);
});

test("Atkinson diffusion produces binary ink without mutating the source field", () => {
  const tone = Float32Array.from([0, .3, .6, .4, .8, 1]);
  const original = tone.slice();
  assert.deepEqual([...atkinson(tone, 3, 2, 0)], [0, 0, 1, 0, 1, 1]);
  assert.deepEqual(tone, original);
  assert.deepEqual([...atkinson(new Float32Array(6), 3, 2, 0)], [0, 0, 0, 0, 0, 0]);
  assert.deepEqual([...atkinson(new Float32Array(6).fill(1), 3, 2, 0)], [1, 1, 1, 1, 1, 1]);
});

test("formatting preserves the real evaluation's fractional percentages", () => {
  assert.equal(formatPercent(.2375), "23.75%");
  assert.equal(formatPercent(.3125), "31.25%");
  assert.equal(formatPercent(.325), "32.5%");
  assert.equal(formatPercent(.3875), "38.75%");
});

test("chapter lookup supports both overview URLs and every chapter", () => {
  assert.equal(chapters.length, 7);
  assert.equal(chapterForPath("/app").slug, "overview");
  for (const chapter of chapters) assert.equal(chapterForPath(chapter.href), chapter);
});

test("typed loaders request all public result files and forward cancellation", async (t) => {
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    requests.push({ url, options });
    return Response.json({ file: url });
  });
  const controller = new AbortController();
  const names = ["curve", "graph", "snapshots", "provenance", "agent", "load", "baselines", "loadtest", "graph_stats"];
  const functions = [
    loaders.loadCurve, loaders.loadGraph, loaders.loadSnapshots,
    loaders.loadProvenance, loaders.loadAgent, loaders.loadLoad,
    loaders.loadBaselines, loaders.loadLoadTest, loaders.loadGraphStats,
  ];
  for (const [index, load] of functions.entries()) {
    const result = await load({ signal: controller.signal });
    assert.deepEqual(result, { file: `/data/${names[index]}.json` });
    assert.equal(requests[index].url, `/data/${names[index]}.json`);
    assert.equal(requests[index].options.signal, controller.signal);
  }
});

test("loaders reject HTTP, JSON, and cancelled-request failures", async (t) => {
  const fetchMock = t.mock.method(globalThis, "fetch", async () => new Response("", { status: 404 }));
  await assert.rejects(loaders.loadCurve(), /curve\.json \(404\)/);
  fetchMock.mock.mockImplementation(async () => new Response("not json"));
  await assert.rejects(loaders.loadGraph(), SyntaxError);
  fetchMock.mock.mockImplementation(async () => { throw new DOMException("Aborted", "AbortError"); });
  await assert.rejects(loaders.loadAgent(), { name: "AbortError" });
});
