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
export function receiptRelation(query: QueryReceipt): string {
  return query.cypher.match(/\[\w*:(\w+)/)?.[1] ?? "Graph query";
}
