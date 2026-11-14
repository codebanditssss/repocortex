import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { checkpointIndex, clampStep, functionName, pathKind, rulerMarks, searchProvenance, shortFunctionName } from "../lib/dashboard.ts";
import { provenanceLines, selectHeroIssue } from "../lib/landing.ts";

const readData = async (name) => JSON.parse(await readFile(new URL(`../public/data/${name}.json`, import.meta.url), "utf8"));
const [curve, provenance] = await Promise.all([readData("curve"), readData("provenance")]);

test("dashboard replay uses the last recorded checkpoint at every step, without interpolated scores", () => {
  const lastStep = curve.curve.at(-1).step;
  for (let step = 0; step <= lastStep; step++) {
    const index = checkpointIndex(curve, step);
    assert.ok(curve.curve[index].step <= step);
    assert.ok(!curve.curve[index + 1] || curve.curve[index + 1].step > step);
  }
  assert.equal(checkpointIndex(curve, lastStep), curve.curve.length - 1);
  assert.deepEqual([-10, 0, 12.7, lastStep, lastStep + 1000, NaN].map((step) => clampStep(step, lastStep)), [0, 0, 13, lastStep, lastStep, 0]);
});

test("Locate indexes all real tickets and supports IDs, functions, paths, case, and phrases", () => {
  assert.equal(provenance.issues.length, provenance.holdout);
  for (const issue of provenance.issues) {
    assert.ok(searchProvenance(provenance, String(issue.ticket)).includes(issue));
    for (const hit of issue.hits) {
      assert.ok(searchProvenance(provenance, hit.file).includes(issue));
      assert.ok(searchProvenance(provenance, hit.uid).includes(issue));
    }
  }
  const sample = provenance.issues[0];
  assert.equal(searchProvenance(provenance, ` #${sample.ticket} `)[0].ticket, sample.ticket);
  assert.ok(searchProvenance(provenance, sample.hits[0].uid.split(":").at(-1).toUpperCase()).some((issue) => issue.ticket === sample.ticket));
  assert.deepEqual(searchProvenance(provenance, ""), []);
  assert.deepEqual(searchProvenance(provenance, "a nonexistent bug report"), []);
});

test("Locate's default hit and receipt preserve captured FIXED_IN evidence", () => {
  const demo = selectHeroIssue(provenance);
  assert.equal(demo.hits[0].rank, 1);
  assert.equal(demo.hits[0].gold, true);
  assert.ok(["FIXED_IN", "SHORTCUT"].includes(pathKind(demo.hits[0].path)));
  assert.ok(demo.hits[0].path.includes("FIXED_IN"));
  assert.ok(shortFunctionName(demo.hits[0]).length > 0);
  assert.ok(functionName(demo.hits[0]).includes("."));
  assert.equal(functionName({ uid: "some/module/function_name" }), "function_name");
  assert.equal(pathKind("dense + bm25"), "dense + bm25");
  assert.equal(pathKind("concept:primary -SHORTCUT-> target"), "SHORTCUT");
  const receipt = provenanceLines(demo, demo.hits[0]).join("\n");
  assert.match(receipt, /FIXED_IN|issue #/);
});

test("a selected non-gold or shortcut hit has its own receipt, not the first gold hit's", () => {
  for (const issue of provenance.issues) {
    for (const hit of issue.hits) {
      const text = provenanceLines(issue, hit).join("\n");
      assert.ok(text.includes(`rank ${hit.rank} / score ${hit.score}`));
      assert.ok(text.includes(`file / ${hit.file}`));
      assert.ok(text.includes(`gold match / ${hit.gold ? "yes" : "no"}`));
      if (hit.path.includes("SHORTCUT")) {
        for (const route of hit.path.split(" | ").filter((part) => part.includes("SHORTCUT"))) assert.ok(text.includes(route));
      }
    }
  }
});

test("ruler marks follow the training length instead of a fixed 320-step scale", () => {
  assert.deepEqual(rulerMarks(1281), [0, 320, 641, 961, 1281]);
  assert.deepEqual(rulerMarks(320), [0, 80, 160, 240, 320]);
  assert.deepEqual(rulerMarks(0), [0, 0, 0, 0, 0]);
});
