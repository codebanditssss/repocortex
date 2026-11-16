export type BackendStatus = { mode: string; connected: boolean; detail?: string };
export type LiveHit = { rank: number; uid: string; file: string; qualname: string; line: number; score: number; path: string };
export type QueryReceipt = { cypher: string; params: Record<string, unknown>; rows: number; limit_reached: boolean };
export type LocateResult = { hits: LiveHit[]; backend: BackendStatus; source: "live" | "replay"; scoring: string; queries: QueryReceipt[] };

const record = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
export function isBackendStatus(value: unknown): value is BackendStatus {
  return record(value) && typeof value.mode === "string" && typeof value.connected === "boolean" && (value.detail === undefined || typeof value.detail === "string");
}
export function isLocateResult(value: unknown): value is LocateResult {
  return record(value) && isBackendStatus(value.backend) && ["live", "replay"].includes(String(value.source)) && typeof value.scoring === "string"
    && Array.isArray(value.hits) && value.hits.every((hit) => record(hit) && Number.isInteger(hit.rank) && typeof hit.score === "number" && Number.isFinite(hit.score) && typeof hit.line === "number" && ["uid", "file", "qualname", "path"].every((key) => typeof hit[key] === "string"))
    && Array.isArray(value.queries) && value.queries.every((query) => record(query) && typeof query.cypher === "string" && record(query.params) && Number.isInteger(query.rows) && Number(query.rows) >= 0 && typeof query.limit_reached === "boolean");
}

export function shortLiveName(hit: LiveHit): string {
  const name = hit.qualname || hit.uid;
  return name.split(".").slice(-2).join(".");
}

export function sourceUrl(hit: LiveHit, snapshot: string): string | null {
  if (!/^[0-9a-f]{40}$/.test(snapshot) || !hit.file || hit.line < 1) return null;
  const parts = hit.file.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) return null;
  const path = parts.map(encodeURIComponent).join("/");
  return `https://github.com/django/django/blob/${snapshot}/${path}#L${Math.floor(hit.line)}`;
}

export function repairBrief(report: string, result: LocateResult, snapshot: string): string {
  const candidates = result.hits.slice(0, 5).map((hit) => {
    const evidence = hit.path ? hit.path.split(" | ").map((path) => `  - ${path}`).join("\n") : "  - No graph path returned.";
    const source = sourceUrl(hit, snapshot);
    return `${hit.rank}. **${hit.qualname || hit.uid}** — \`${hit.file}:${hit.line}\` — score ${hit.score.toFixed(3)}${source ? `\n   Source: ${source}` : ""}\n   Evidence:\n${evidence}`;
  }).join("\n\n");
  const relations = new Map<string, number>();
  for (const query of result.queries) {
    const relation = receiptRelation(query);
    relations.set(relation, (relations.get(relation) ?? 0) + 1);
  }
  const receiptSummary = [...relations].map(([relation, count]) => `${relation} (${count})`).join(", ") || "none (cached result)";
  const rows = result.queries.reduce((total, query) => total + query.rows, 0);
  const queryExamples = [...new Set(result.queries.map((query) => query.cypher))].slice(0, 3);
  const querySection = queryExamples.length ? `\n\nRepresentative Cypher receipts:\n${queryExamples.map((cypher) => `\n\`\`\`cypher\n${cypher}\n\`\`\``).join("\n")}` : "";
  return `# RepoCortex repair brief

## Bug report
${report.trim()}

## Candidate functions
${candidates || "No candidate functions were returned."}

## Retrieval receipt
- Repository: django/django at ${snapshot}
- Mode: ${result.source === "live" ? "live HydraDB structural traversal + saved fix history" : "cached structural graph + saved fix history"}
- Database queries: ${result.queries.length}; rows returned: ${rows}
- Relationship reads: ${receiptSummary}${querySection}

Scores rank candidates; they are not probabilities. Inspect the evidence and source before editing. After tests pass, submit the reviewed diff through the local learn_from_fix workflow.`;
}

export function estimatedTokens(text: string): number {
  return Math.max(1, Math.ceil(text.length / 4));
}

export function receiptRelation(query: QueryReceipt): string {
  return query.cypher.match(/\[\w*:(\w+)/)?.[1] ?? "Graph query";
}
