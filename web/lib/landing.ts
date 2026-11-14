import type { CurveData, ProvenanceData, ProvenanceHit, ProvenanceIssue, SnapshotsData } from "./data.ts";

export type LandingMetric = "file_acc@1" | "function_acc@10";
export const metricLabels: Record<LandingMetric, string> = {
  "file_acc@1": "File Acc@1",
  "function_acc@10": "Function Acc@10",
};

/** Leave a separate label rail. The series never shares space with its label. */
export const chartFrame = { left: 58, right: 530, top: 44, bottom: 320, width: 720, height: 395 };

export function chartModel(data: CurveData, metric: LandingMetric, frame = chartFrame) {
  const values = [...data.curve.map((point) => point[metric]), ...Object.values(data.baselines).map((point) => point[metric])];
  const low = Math.floor((Math.min(...values) - .025) * 20) / 20;
  const high = Math.ceil((Math.max(...values) + .025) * 20) / 20;
  const ticks = Array.from({ length: Math.round((high - low) / .05) + 1 }, (_, i) => Number((low + i * .05).toFixed(2)));
  const { left, right, top, bottom } = frame;
  return {
    low, high, ticks,
    x: (step: number) => left + step / data.train * (right - left),
    y: (value: number) => bottom - (value - low) / (high - low) * (bottom - top),
  };
}

export function chartSeries(data: CurveData, metric: LandingMetric, index: number, frame = chartFrame) {
  const { y } = chartModel(data, metric, frame);
  const lines = [
    { id: "repo", label: "RepoCortex", value: data.curve[index][metric], stroke: "var(--red)", dash: undefined },
    { id: "dense", label: "Dense vectors", value: data.baselines.dense[metric], stroke: "var(--ink2)", dash: "6 5" },
    { id: "bm25", label: "BM25", value: data.baselines.bm25[metric], stroke: "var(--ink2)", dash: "1 4" },
    { id: "frozen", label: "Frozen graph", value: data.baselines.frozen[metric], stroke: "var(--ink)", dash: undefined },
  ].map((line) => ({ ...line, labelY: y(line.value) })).sort((a, b) => a.labelY - b.labelY);
  // The function metric has coincident series. Space their labels in the rail,
  // without moving the data, and use small leaders to keep the mapping explicit.
  lines.forEach((line, i) => {
    if (i) line.labelY = Math.max(line.labelY, lines[i - 1].labelY + 50);
  });
  const overflow = Math.max(0, lines[lines.length - 1].labelY - frame.bottom);
  lines.forEach((line) => { line.labelY -= overflow; });
  return lines;
}

export function selectHeroIssue(data: Pick<ProvenanceData, "issues">): ProvenanceIssue {
  const issue = data.issues.find((issue) => issue.hits[0]?.gold && issue.hits[0].path.includes("FIXED_IN"))
    ?? data.issues.find((issue) => issue.hits.some((hit) => hit.gold && hit.path.includes("FIXED_IN")))
    ?? data.issues.find((issue) => issue.hits.some((hit) => hit.gold));
  if (!issue) throw new Error("No measured provenance issue is available");
  return issue;
}

export const hitSymbol = (hit: ProvenanceHit) => hit.uid.split(":").at(-1)!;

/** Parse only captured FIXED_IN evidence. Other paths retain their original text. */
export function fixedInRoutes(path: string) {
  return [...path.matchAll(/issue #(\d+) sim ([\d.]+) -FIXED_IN-> (.+?) \(w ([\d.]+)\)/g)]
    .map((match) => ({ ticket: Number(match[1]), similarity: match[2], target: match[3], weight: match[4] }));
}

export function provenanceLines(issue: ProvenanceIssue, selectedHit?: ProvenanceHit): string[] {
  const hit = selectedHit ?? issue.hits.find((hit) => hit.gold) ?? issue.hits[0];
  const lines = [`held-out issue #${issue.ticket}`, "│"];
  const routes = fixedInRoutes(hit.path);
  if (routes.length) {
    routes.forEach((route, index) => {
      const branch = index === routes.length - 1 ? "└" : "├";
      lines.push(
        `${branch}─ issue #${route.ticket} / similarity ${route.similarity}`,
        `   └─ FIXED_IN / weight ${route.weight}`,
        `      └─ ${route.target}`,
      );
    });
    if (hit.path.includes("SHORTCUT")) {
      lines.push(...hit.path.split(" | ").filter((path) => path.includes("SHORTCUT")).map((path) => `└─ ${path}`));
    }
  } else {
    // SHORTCUT and hybrid-search paths are printed verbatim, never reinterpreted.
    lines.push(`└─ ${hit.path}`, `   └─ ${hitSymbol(hit)}`);
  }
  lines.push(
    "", `rank ${hit.rank} / score ${hit.score}`,
    `file / ${hit.file}`,
    `gold match / ${hit.gold ? "yes" : "no"}`,
    "", "gold functions",
    ...issue.gold.map((uid) => `└─ ${uid}`),
  );
  return lines;
}

/** Synthetic snapshots have their own cadence, not the measured curve's steps. */
export function snapshotAtStep(snapshots: SnapshotsData, step: number) {
  const keys = Object.keys(snapshots.checkpoints).map(Number).filter((value) => value <= step);
  return snapshots.checkpoints[String(Math.max(0, ...keys))];
}
