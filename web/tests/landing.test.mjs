import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { chartFrame, chartModel, chartSeries, fixedInRoutes, hitSymbol, provenanceLines, selectHeroIssue, snapshotAtStep } from "../lib/landing.ts";
import { scopeEvidence } from "../lib/scope-evidence.ts";

const readData = async (name) => JSON.parse(await readFile(new URL(`../public/data/${name}.json`, import.meta.url), "utf8"));
const readResult = async (name) => JSON.parse(await readFile(new URL(`../../results/${name}`, import.meta.url), "utf8"));
const [data, provenance] = await Promise.all([readData("curve"), readData("provenance")]);

test("scope of evidence stays locked to the positive and null result artifacts", async () => {
  const [django, starlette, repair] = await Promise.all([
    readResult("baselines.json"),
    readResult("starlette_prequential_result.json"),
    readResult("learning_repair_followup.json"),
  ]);
  const frozen = django.ablations["learning off"].final["function_acc@10"];
  const learned = django.ablations.full.final["function_acc@10"];
  const starletteFlat = starlette.fixed_holdout_checkpoints.flat_memory.at(-1).summary["function_acc@10"];
  const starletteLearned = starlette.fixed_holdout_checkpoints.learned_graph.at(-1).summary["function_acc@10"];
  const ties = starlette.primary_final_holdout_learned_minus_flat["function_acc@10"].exact_discordant_fix_test.ties;

  assert.deepEqual(scopeEvidence.map(({ study, result, delta, conclusion }) => ({ study, result, delta, conclusion })), [
    { study: "Django retrospective", result: `${(frozen * 100).toFixed(1)}% → ${(learned * 100).toFixed(1)}%`, delta: `+${((learned - frozen) * 100).toFixed(1)}pp`, conclusion: "Demonstrated on this split" },
    { study: "Starlette prospective", result: `${(starletteFlat * 100).toFixed(1)}% vs ${(starletteLearned * 100).toFixed(1)}%`, delta: `${((starletteLearned - starletteFlat) * 100).toFixed(1)}pp · ${ties} ties`, conclusion: "No demonstrated advantage" },
    { study: "Repair outcomes", result: `${repair.learned_test_repairs}/2 vs ${repair.frozen_test_repairs}/2`, delta: "Same repair count", conclusion: "No demonstrated advantage" },
  ]);
  assert.deepEqual(scopeEvidence.map(({ href }) => href), [
    "https://github.com/codebanditssss/repocortex/blob/main/results/baselines.json",
    "https://github.com/codebanditssss/repocortex/blob/main/results/starlette_prequential.md",
    "https://github.com/codebanditssss/repocortex/blob/main/results/learning_repair_followup.md",
  ]);
});

test("landing plots real checkpoints on one honest scale, with room for every baseline", () => {
  for (const metric of ["file_acc@1", "function_acc@10"]) {
    const model = chartModel(data, metric);
    assert.equal(model.x(0), chartFrame.left);
    assert.equal(model.x(data.train), chartFrame.right);
    assert.ok(model.low < Math.min(...data.curve.map((point) => point[metric])));
    assert.ok(model.high > Math.max(...Object.values(data.baselines).map((point) => point[metric])));
    for (const value of [...data.curve, ...Object.values(data.baselines)]) {
      assert.ok(model.y(value[metric]) > chartFrame.top);
      assert.ok(model.y(value[metric]) < chartFrame.bottom);
    }
    assert.equal(model.ticks[0], model.low);
    assert.equal(model.ticks.at(-1), model.high);
    assert.ok(model.y(.4) < model.y(.3), "higher accuracy must appear higher, not lower");
  }
  assert.equal(data.curve[0]["file_acc@1"], data.baselines.frozen["file_acc@1"]);
  assert.ok(data.curve.at(-1)["file_acc@1"] > data.curve[0]["file_acc@1"]);
  assert.equal(data.curve[0]["function_acc@10"], data.baselines.frozen["function_acc@10"]);
  assert.ok(data.curve.at(-1)["function_acc@10"] > data.curve[0]["function_acc@10"]);
  const fileScores = data.curve.map((point) => point["file_acc@1"]);
  assert.ok(fileScores.some((value, i) => i && value < fileScores[i - 1]), "preserve measured dips");
  for (const metric of ["file_acc@1", "function_acc@10"]) {
    assert.ok(data.curve.at(-1)[metric] > data.baselines.dense[metric]);
  }
});

test("all four chart labels remain separated, including coincident series at every step", () => {
  for (const metric of ["file_acc@1", "function_acc@10"]) {
    for (let index = 0; index < data.curve.length; index++) {
      const series = chartSeries(data, metric, index);
      assert.equal(series.length, 4);
      assert.equal(series.find((line) => line.id === "repo").value, data.curve[index][metric]);
      for (const id of ["frozen", "dense", "bm25"]) {
        assert.equal(series.find((line) => line.id === id).value, data.baselines[id][metric]);
      }
      for (let i = 1; i < series.length; i++) assert.ok(series[i].labelY - series[i - 1].labelY >= 50 - 1e-9);
      assert.ok(series[0].labelY >= chartFrame.top);
      assert.ok(series.at(-1).labelY <= chartFrame.bottom);
      assert.ok(chartFrame.right + 35 < chartFrame.width);
    }
  }
});

test("provenance receipts parse measured paths without inventing edges or scores", () => {
  for (const issue of provenance.issues) {
    const text = provenanceLines(issue).join("\n");
    const hit = issue.hits.find((hit) => hit.gold) ?? issue.hits[0];
    assert.ok(text.includes(`held-out issue #${issue.ticket}`));
    for (const value of [hitSymbol(hit), hit.file, `rank ${hit.rank}`, `score ${hit.score}`, `gold match / ${hit.gold ? "yes" : "no"}`]) {
      assert.ok(text.includes(value), value);
    }
    for (const path of fixedInRoutes(hit.path)) {
      for (const value of [`issue #${path.ticket}`, `similarity ${path.similarity}`, `weight ${path.weight}`, path.target]) {
        assert.ok(text.includes(value), value);
      }
    }
    if (!fixedInRoutes(hit.path).length) assert.ok(text.includes(hit.path));
    for (const uid of issue.gold) assert.ok(text.includes(uid));
    assert.doesNotMatch(text, /fixture|past fixes/);
    assert.doesNotMatch(text, /\u2014|\p{Extended_Pictographic}/u);
  }
});

test("the landing hero is a measured rank-one gold hit with FIXED_IN evidence", () => {
  const issue = selectHeroIssue(provenance);
  assert.equal(issue.hits[0].gold, true);
  assert.equal(issue.hits[0].rank, 1);
  assert.ok(issue.hits[0].path.includes("FIXED_IN"));
  assert.ok(fixedInRoutes(issue.hits[0].path).length >= 1);
  assert.deepEqual(fixedInRoutes("dense + bm25"), []);
  assert.deepEqual(fixedInRoutes("concept:field -SHORTCUT-> target (hits 3, misses 0)"), []);
});

test("every replay step uses the nearest earlier synthetic snapshot, not a reset", async () => {
  const snapshots = await readData("snapshots");
  const steps = data.curve.map((point) => snapshotAtStep(snapshots, point.step).step);
  assert.equal(steps[0], 0);
  assert.ok(steps.every((step, i) => i === 0 || step >= steps[i - 1]));
  assert.ok(steps.at(-1) <= 320);
});
