import type { CurveData, ProvenanceData, ProvenanceHit } from "./data.ts";

/** Only recorded checkpoints supply scores, even when the playhead is between them. */
export function checkpointIndex(data: Pick<CurveData, "curve">, step: number) {
  let index = 0;
  for (let i = 0; i < data.curve.length; i++) {
    if (data.curve[i].step <= step) index = i;
    else break;
  }
  return index;
}

export function clampStep(step: number, total: number) {
  return Math.max(0, Math.min(total, Math.round(Number.isFinite(step) ? step : 0)));
}

export function functionName(hit: Pick<ProvenanceHit, "uid">) {
  return hit.uid.split(":").at(-1)?.split("/").at(-1) || hit.uid;
}

export function shortFunctionName(hit: Pick<ProvenanceHit, "uid">) {
  return functionName(hit).split(".").slice(-2).join(".");
}

export function pathKind(path: string) {
  if (path.includes("SHORTCUT")) return "SHORTCUT";
  if (path.includes("FIXED_IN")) return "FIXED_IN";
  return path;
}

/**
 * This is a local evidence index, not semantic search. All words must occur
 * in the issue's captured ticket, function IDs, or filenames.
 */
export function searchProvenance(data: Pick<ProvenanceData, "issues">, query: string) {
  const terms = query.trim().toLowerCase().replace(/^#(?=\d)/, "").split(/\s+/).filter(Boolean);
  if (!terms.length) return [];
  return data.issues.filter((issue) => {
    const text = [String(issue.ticket), ...issue.hits.flatMap((hit) => [hit.uid, hit.file])].join(" ").toLowerCase();
    return terms.every((term) => text.includes(term));
  });
}

/** Evenly spaced labels for the learning-pass step ruler. */
export function rulerMarks(total: number, count = 5) {
  const end = Math.max(0, total);
  if (count <= 1) return [end];
  return Array.from({ length: count }, (_, i) => Math.round((end * i) / (count - 1)));
}
