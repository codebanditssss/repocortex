export interface EvalMetrics {
  n: number;
  "function_acc@5": number;
  "function_acc@10": number;
  "file_acc@1": number;
  "file_acc@5": number;
  mrr: number;
}

export interface CurvePoint extends EvalMetrics {
  step: number;
}

export interface CurveData {
  source: string;
  placeholder: false;
  snapshot: string;
  scope: string[];
  backend: string;
  hops: number;
  train: number;
  holdout: number;
  truncated: { nodes: string[]; edges: string[] };
  baselines: Record<"bm25" | "dense" | "frozen", EvalMetrics>;
  curve: CurvePoint[];
  operators: {
    edge_reweight: number;
    path_compression: number;
    gap_ingestion: number;
    entity_merge_split: number;
  };
  params: {
    bm25_mix: number;
    memory_lam: number;
    memory_thresh: number;
    memory_k: number;
    shortcut_lam: number;
    graph_mix?: number;
    shortcut_min_support?: number;
    shortcut_min_precision?: number;
  };
  note: string;
}

export type EdgeType = "CALLS" | "IMPORTS" | "CO_CHANGED" | "SHORTCUT";

export interface LayoutNode {
  id: string;
  label: string;
  file: string;
  x: number;
  y: number;
}

export interface LayoutEdge {
  /** Zero-based indices into graph.nodes, not backend entity IDs. */
  s: number;
  t: number;
  type: EdgeType;
  w: number;
}

interface PlaceholderData {
  placeholder: true;
  note: string;
}

export interface GraphStats {
  snapshot: string;
  backend: string;
  local_nodes: number;
  local_edges: number;
  db_nodes: number;
  db_edges: number;
  truncated: { nodes: string[]; edges: string[] };
  labels: Record<string, number>;
}

export interface GraphStatsData extends GraphStats {
  source: string;
  placeholder: false;
}

export interface GraphData extends PlaceholderData {
  seed: number;
  graph_stats: GraphStats;
  nodes: LayoutNode[];
  edges: LayoutEdge[];
}

export interface Checkpoint {
  step: number;
  edge_deltas: Pick<LayoutEdge, "s" | "t" | "w">[];
  shortcuts: LayoutEdge[];
  gap_fills: LayoutNode[];
  merges: { from: string[]; into: string }[];
}

export interface SnapshotsData extends PlaceholderData {
  checkpoints: Record<string, Checkpoint>;
}

export interface ProvenanceHit {
  rank: number;
  uid: string;
  file: string;
  score: number;
  gold: boolean;
  path: string;
}

export interface ProvenanceIssue {
  ticket: number;
  gold: string[];
  hits: ProvenanceHit[];
}

export interface ProvenanceData {
  source: string;
  placeholder: false;
  holdout: number;
  hits_with_fixed_in: number;
  hits_with_shortcut: number;
  hits_with_graph?: number;
  issues: ProvenanceIssue[];
}

interface AgentTrace {
  tokens: number;
  turns: number;
  files_read: number;
}

export interface AgentData extends PlaceholderData {
  ticket: string;
  without: AgentTrace;
  with: AgentTrace & {
    tool_calls: {
      name: string;
      args: Record<string, string | number | boolean>;
      result_summary: string;
    }[];
  };
}

export interface LoadTest {
  source: string;
  placeholder: false;
  tool: string;
  users: number;
  spawn_rate: number;
  duration_s: number;
  host: string;
  endpoint: string;
  requests: number;
  failures: number;
  avg_ms: number;
  min_ms: number;
  max_ms: number;
  median_ms: number;
  p95_ms: number;
  p99_ms: number;
  rps: number;
}

/** Compatibility view in load.json; measured fields are the source of truth. */
export interface LoadData extends LoadTest {
  note: string;
  unit: "ms";
  scenarios: {
    concurrent_agents: number;
    p50: number;
    p95: number;
    p99: number;
    rps: number;
    requests: number;
    failures: number;
  }[];
}

export interface DataFiles {
  curve: CurveData;
  baselines: CurveData;
  graph: GraphData;
  graph_stats: GraphStatsData;
  snapshots: SnapshotsData;
  provenance: ProvenanceData;
  agent: AgentData;
  load: LoadData;
  loadtest: LoadTest;
}

/** Browser loaders for measured results and labeled fixtures. Server pages can import JSON. */
export async function loadData<K extends keyof DataFiles>(
  name: K,
  options?: RequestInit,
): Promise<DataFiles[K]> {
  const response = await fetch(`/data/${name}.json`, options);
  if (!response.ok) {
    throw new Error(`Could not load ${name}.json (${response.status})`);
  }
  const data: unknown = await response.json();
  return data as DataFiles[K];
}

export const loadCurve = (options?: RequestInit) => loadData("curve", options);
export const loadBaselines = (options?: RequestInit) => loadData("baselines", options);
export const loadGraph = (options?: RequestInit) => loadData("graph", options);
export const loadGraphStats = (options?: RequestInit) => loadData("graph_stats", options);
export const loadSnapshots = (options?: RequestInit) => loadData("snapshots", options);
export const loadProvenance = (options?: RequestInit) => loadData("provenance", options);
export const loadAgent = (options?: RequestInit) => loadData("agent", options);
export const loadLoad = (options?: RequestInit) => loadData("load", options);
export const loadLoadTest = (options?: RequestInit) => loadData("loadtest", options);
