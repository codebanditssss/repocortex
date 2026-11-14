import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { selectHeroIssue } from "../lib/landing.ts";

const readData = async (name) =>
  JSON.parse(await readFile(new URL(`../public/data/${name}.json`, import.meta.url), "utf8"));
const [evaluation, graph, snapshots, provenance, agent, load, loadTest] = await Promise.all(
  ["curve", "graph", "snapshots", "provenance", "agent", "load", "loadtest"].map(readData),
);

test("the full curve matches the current backend results", () => {
  assert.equal(evaluation.placeholder, false);
  assert.equal(evaluation.source, "results/baselines.json + results/curve.json");
  assert.equal(evaluation.snapshot, "f24f38c6b2825f15628c07bf2892f1664eed9361");
  assert.deepEqual(evaluation.scope, ["django", "tests"]);
  assert.equal(evaluation.backend, "bolt");
  assert.equal(evaluation.hops, 2);
  assert.equal(evaluation.train, 1281);
  assert.equal(evaluation.holdout, 319);
  assert.equal(evaluation.curve.length, 15);
  assert.equal(evaluation.curve[0].step, 0);
  assert.equal(evaluation.curve.at(-1).step, 1281);
  assert.ok(evaluation.curve.every((point) => point.n === 319));
  const last = evaluation.curve.at(-1);
  assert.equal(last["function_acc@10"], 0.4827586206896552);
  assert.equal(last["file_acc@1"], 0.445141065830721);
  assert.deepEqual(evaluation.operators, {
    edge_reweight: 3407, path_compression: 535, gap_ingestion: 1667, entity_merge_split: 33,
  });
  assert.equal(evaluation.params.bm25_mix, .1);
  assert.equal(evaluation.params.memory_k, 5);
});

test("all baseline metrics retain the exact supplied values", () => {
  assert.equal(evaluation.baselines.bm25.n, 319);
  assert.equal(evaluation.baselines.dense.n, 319);
  assert.equal(evaluation.baselines.frozen.n, 319);
  assert.equal(evaluation.baselines.dense["function_acc@10"], evaluation.baselines.dense["function_acc@10"]);
  for (const name of ["bm25", "dense", "frozen"]) {
    const row = evaluation.baselines[name];
    for (const key of ["function_acc@5", "function_acc@10", "file_acc@1", "file_acc@5", "mrr"]) {
      assert.ok(Number.isFinite(row[key]));
    }
  }
  // Learned Acc@10 beats dense. Frozen is the unlearned hybrid and matches step 0.
  assert.ok(evaluation.curve.at(-1)["function_acc@10"] > evaluation.baselines.dense["function_acc@10"]);
  assert.equal(evaluation.curve[0]["function_acc@10"], evaluation.baselines.frozen["function_acc@10"]);
});

test("graph stats are real, while the bounded layout is explicitly synthetic", () => {
  assert.equal(graph.placeholder, true);
  assert.match(graph.note, /stand-in/);
  assert.equal(graph.seed, 99);
  assert.deepEqual(graph.graph_stats, {
    snapshot: evaluation.snapshot, backend: "bolt",
    local_nodes: 46443, local_edges: 138150, db_nodes: 46443, db_edges: 138150,
    truncated: { nodes: [], edges: [] },
    labels: { Repo: 1, File: 2605, Function: 8834, Class: 10510, Test: 21603, Concept: 2268, Symptom: 622 },
  });
  assert.ok(graph.nodes.length >= 400 && graph.nodes.length <= 800);
  assert.equal(new Set(graph.nodes.map((node) => node.id)).size, graph.nodes.length);
  for (const node of graph.nodes) {
    assert.ok(node.label && node.file && node.id);
    assert.ok(Number.isFinite(node.x) && node.x >= 0 && node.x <= 1);
    assert.ok(Number.isFinite(node.y) && node.y >= 0 && node.y <= 1);
  }
  assert.deepEqual(new Set(graph.edges.map((edge) => edge.type)), new Set([
    "CALLS", "IMPORTS", "CO_CHANGED", "SHORTCUT",
  ]));
  for (const edge of graph.edges) {
    assert.ok(Number.isInteger(edge.s) && graph.nodes[edge.s]);
    assert.ok(Number.isInteger(edge.t) && graph.nodes[edge.t]);
    assert.notEqual(edge.s, edge.t);
    assert.ok(edge.w > 0 && edge.w <= 1);
  }
});

test("synthetic snapshots retain their independent fixture cadence and disclose it", () => {
  assert.equal(snapshots.placeholder, true);
  assert.match(snapshots.note, /fixture cadence/);
  assert.deepEqual(Object.keys(snapshots.checkpoints).map(Number), [0, 50, 100, 150, 200, 250, 300, 320]);
  assert.deepEqual(snapshots.checkpoints["0"].edge_deltas, []);
  const realPairs = new Set(graph.edges.map((edge) => `${edge.s}:${edge.t}`));
  for (const [key, checkpoint] of Object.entries(snapshots.checkpoints)) {
    assert.equal(checkpoint.step, Number(key));
    for (const field of ["shortcuts", "gap_fills", "merges"]) {
      assert.deepEqual(checkpoint[field], []);
    }
    for (const edge of checkpoint.edge_deltas) {
      assert.ok(realPairs.has(`${edge.s}:${edge.t}`));
      assert.ok(edge.w > 0 && edge.w <= 1);
    }
  }
});

test("measured provenance retains held-out issues and captured hit paths", () => {
  assert.equal(provenance.placeholder, false);
  assert.equal(provenance.source, "results/provenance.json");
  assert.equal(provenance.holdout, 319);
  assert.equal(provenance.issues.length, 319);
  assert.ok(new Set(provenance.issues.map((issue) => issue.ticket)).size >= 300);
  assert.equal(provenance.hits_with_fixed_in, 314);
  assert.equal(provenance.hits_with_shortcut, 63);
  for (const issue of provenance.issues) {
    assert.ok(Number.isInteger(issue.ticket));
    assert.ok(issue.gold.length && issue.hits.length);
    for (const hit of issue.hits) {
      assert.ok(Number.isInteger(hit.rank) && hit.rank > 0);
      assert.ok(hit.uid.includes(hit.file));
      assert.equal(typeof hit.path, "string");
      assert.ok(hit.path.length);
      assert.ok(Number.isFinite(hit.score));
      assert.equal(hit.gold, issue.gold.includes(hit.uid));
    }
  }
  const hero = selectHeroIssue(provenance);
  assert.equal(hero.hits[0].rank, 1);
  assert.equal(hero.hits[0].gold, true);
  assert.ok(hero.hits[0].path.includes("FIXED_IN"));
});

test("agent traces remain explicitly illustrative and independent of real issues", () => {
  assert.equal(agent.placeholder, true);
  assert.ok(agent.note.length > 20);
  assert.equal(typeof agent.ticket, "string");
  for (const trace of [agent.with, agent.without]) {
    assert.ok(trace.tokens > 0 && trace.turns > 0 && trace.files_read > 0);
  }
  assert.ok(agent.with.tool_calls.every((call) => call.name && call.args && call.result_summary));
});

test("load data is exactly one measured Locust run, not a fabricated sweep", () => {
  assert.deepEqual(loadTest, {
    source: "results/loadtest.json", placeholder: false, tool: "locust 2.47.0",
    users: 8, spawn_rate: 4, duration_s: 20, host: "http://127.0.0.1:8765",
    endpoint: "POST /locate", requests: 1251, failures: 0,
    avg_ms: 23, min_ms: 8, max_ms: 69, median_ms: 21, p95_ms: 44, p99_ms: 56, rps: 62.94,
  });
});

test("public result aliases and standalone graph statistics agree", async () => {
  assert.deepEqual(await readData("baselines"), evaluation);
  const { note, scenarios, unit, ...measuredLoad } = load;
  assert.deepEqual(measuredLoad, loadTest);
  assert.match(note, /One locust run/);
  assert.equal(unit, "ms");
  assert.deepEqual(scenarios, [{
    concurrent_agents: 8, p50: 21, p95: 44, p99: 56, rps: 62.94, requests: 1251, failures: 0,
  }]);
  const { source, placeholder, ...stats } = await readData("graph_stats");
  assert.equal(source, "results/graph_stats.json");
  assert.equal(placeholder, false);
  assert.deepEqual(stats, graph.graph_stats);
});
