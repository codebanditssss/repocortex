"use client";

import { useEffect, useRef, useState } from "react";
import { copyText } from "@/lib/clipboard";
import { estimatedTokens, isBackendStatus, isLocateResult, receiptRelation, repairBrief, shortLiveName, sourceUrl, type BackendStatus, type LocateResult, type QueryReceipt } from "@/lib/live";
import stats from "@/public/data/graph_stats.json";

const examples = [
  { label: "Query compilation", report: "QuerySet union loses ordering when combined with values_list. The SQL compiler raises an error when ordering by a column missing from the selected fields." },
  { label: "Timezones", report: "With USE_TZ enabled, filtering a DateTimeField by a date near midnight returns the wrong records. The active timezone differs from UTC. Where does Django convert the datetime before extracting its date?" },
  { label: "Migrations", report: "Renaming a model field in a migration unexpectedly removes and recreates the column instead of preserving its values. Where does Django detect renamed fields and generate the schema operation?" },
];

export function LiveLocate() {
  const [report, setReport] = useState("");
  const [status, setStatus] = useState<BackendStatus | null>(null);
  const [statusRevision, setStatusRevision] = useState(0);
  const [result, setResult] = useState<LocateResult | null>(null);
  const [pending, setPending] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const [copyStatus, setCopyStatus] = useState("");
  const request = useRef<AbortController | null>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (new URLSearchParams(window.location.search).has("focus")) composer.current?.focus();
    const handle = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() !== "k" || event.ctrlKey || event.metaKey || event.altKey || (event.target as HTMLElement)?.closest("input,textarea,select,[contenteditable=true]") || document.querySelector("dialog[open]")) return;
      event.preventDefault(); composer.current?.focus();
    };
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/status", { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]) }).then((response) => {
      if (!response.ok) throw new Error("Service status unavailable");
      return response.json();
    }).then((value) => {
      setStatus(isBackendStatus(value) ? value : { mode: "unavailable", connected: false });
    }).catch(() => { if (!controller.signal.aborted) setStatus({ mode: "unavailable", connected: false }); });
    return () => controller.abort();
  }, [statusRevision]);
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    if (!pending) return;
    const started = Date.now();
    const interval = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(interval);
  }, [pending]);

  function editReport(value: string) {
    setReport(value);
    setResult(null);
    setError("");
    setCopyStatus("");
  }

  async function locate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || !report.trim()) return;
    const controller = new AbortController();
    request.current = controller;
    setPending(true); setElapsed(0); setError(""); setResult(null);
    try {
      const response = await fetch("/api/locate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ report, k: 10 }), signal: AbortSignal.any([controller.signal, AbortSignal.timeout(65000)]) });
      const value = await response.json();
      if (!response.ok) throw new Error(typeof value.error === "string" ? value.error : "The search failed. Please try again.");
      if (!isLocateResult(value)) throw new Error("The search returned an incomplete result.");
      setResult(value); setStatus(value.backend);
    } catch (failure) {
      if (!controller.signal.aborted) {
        try {
          const health = await fetch("/api/status", { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]) });
          const value: unknown = await health.json();
          setStatus(isBackendStatus(value) ? value : { mode: "unavailable", connected: false });
        } catch {
          if (!controller.signal.aborted) setStatus({ mode: "unavailable", connected: false });
        }
      }
      setError(controller.signal.aborted ? "Search cancelled. Your report is still here." : failure instanceof Error && failure.name === "TimeoutError" ? "The search timed out. Please try again." : failure instanceof Error ? failure.message : "The search failed. Please try again.");
    } finally { setPending(false); request.current = null; }
  }

  const bounded = result?.queries.filter((query) => query.limit_reached).length ?? 0;
  const receiptGroups = new Map<string, { query: QueryReceipt; index: number }[]>();
  result?.queries.forEach((query, index) => {
    const relation = receiptRelation(query);
    const entries = receiptGroups.get(relation) ?? [];
    entries.push({ query, index });
    receiptGroups.set(relation, entries);
  });
  return <section id="fresh-search" className="live-locate" aria-labelledby="live-locate-title" tabIndex={-1}>
    <div className="section-rule"><h2 id="live-locate-title">Find the <i>functions.</i></h2><span className={`cap live-status${status?.connected ? " is-connected" : ""}`} role="status">{status === null ? "Checking service…" : status.connected ? "HydraDB connected" : status.mode === "replay" ? "Cached graph mode" : "Status unavailable"}</span></div>
    {status !== null && !status.connected && <div className="live-availability" role="note"><p>{status.mode === "replay" ? "Search uses a cached graph; live query receipts are unavailable." : "Cannot verify the live service. Retry or browse saved results."}</p><div><button type="button" className="underlined-control" disabled={pending} onClick={() => { setStatus(null); setStatusRevision((value) => value + 1); }}>Retry connection</button><a className="underlined-control" href="#saved-evidence">Browse saved evidence →</a></div></div>}
    <div className="live-locate-grid"><form onSubmit={locate}>
      <div className="ticket-sheet"><div className="ticket-sheet-head"><label htmlFor="live-report">What is going wrong in Django?</label><span><kbd>K</kbd> to edit</span></div><textarea ref={composer} id="live-report" value={report} disabled={pending} onChange={(event) => editReport(event.target.value)} onKeyDown={(event) => {
        if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); }
      }} rows={5} maxLength={12000} required placeholder="Describe the error, expected behavior, and the code involved…" aria-describedby="live-search-help" /></div>
      <div className="locate-options"><span>repo <u>django</u></span><button className="btn" type="submit" disabled={pending || !report.trim()}>{pending ? "Tracing the graph…" : "Find functions →"}</button></div>
      <p className="live-keyboard-hint">Ctrl / ⌘ + Enter to search</p>
      <p id="live-search-help" className="figure-note">Search the indexed Django snapshot. Results label live graph reads and saved fix history.</p>
      <div className="live-examples"><span className="sc">Try a report</span><div>{examples.map((example) => <button className="underlined-control" type="button" disabled={pending} key={example.label} onClick={() => { editReport(example.report); composer.current?.focus(); }}>{example.label} →</button>)}</div></div>
    </form><div className="live-search-results" aria-busy={pending}>
      {error && <div className="live-error" role="alert"><strong>Search paused</strong><p>{error}</p>{status?.connected && <a className="underlined-control" href="#saved-evidence">Browse saved evidence →</a>}</div>}
      {pending && <div className="live-progress"><span className="sc" role="status">Searching · {elapsed}s elapsed</span><p>Ranking functions and reading graph relationships.</p><button type="button" className="underlined-control" onClick={() => request.current?.abort()}>Cancel search</button></div>}
      {!result && !pending && !error && <div className="live-empty"><h3>Candidate functions appear here.</h3><p>Enter a bug report or choose an example.</p></div>}
      {result && <><div className="live-result-heading"><h3>Functions to investigate</h3><div className="live-result-tools"><span className="sc" role="status">{result.hits.length} candidates</span><button type="button" className="underlined-control" onClick={async () => {
        const brief = repairBrief(report, result, stats.snapshot);
        setCopyStatus(await copyText(brief) ? `Repair brief copied · about ${estimatedTokens(brief)} tokens` : "Automatic copy is blocked. Select a result and copy its evidence manually.");
      }}>{copyStatus.startsWith("Repair brief copied") ? "Copied repair brief" : "Copy repair brief"}</button></div></div>
        <p className="live-copy-status" role="status">{copyStatus}</p>
        <div className="live-provenance"><span>{result.source === "live" ? "Live structural graph" : "Cached structural graph"}</span><span>Saved fix history</span></div><p className="figure-note">Open a function to inspect its evidence. Scores rank candidates; they are not probabilities.</p>
        <ol className="ranked-hits live-ranked-hits">{result.hits.map((hit) => {
          const source = sourceUrl(hit, stats.snapshot);
          return <li key={`${hit.rank}-${hit.uid}`}><details><summary><span className="hit-rank">{String(hit.rank).padStart(2, "0")}</span><span className="hit-function"><strong title={hit.qualname || hit.uid}>{shortLiveName(hit)}</strong><small>{hit.file}:{hit.line}</small></span><span className="live-score"><span className="num">{hit.score.toFixed(3)}</span><small>score</small></span><span className="live-expand" aria-hidden="true">+</span></summary><div className="live-hit-path"><span className="sc">Why this function surfaced</span><ul>{hit.path ? hit.path.split(" | ").map((path, index) => <li key={index}>{path}</li>) : <li>No graph path returned for this candidate.</li>}</ul><div className="live-hit-actions">{source && <a className="underlined-control" href={source} target="_blank" rel="noreferrer">Open source at indexed snapshot ↗</a>}<details className="live-function-id"><summary>Full function identifier</summary><code>{hit.uid}</code></details></div></div></details></li>;
        })}</ol>
        {!result.hits.length && <p>No functions matched this report. Add an error message or relevant API name and try again.</p>}
        <details className="live-query-receipts">
          <summary><span>Database query receipts</span><span className="num">{result.queries.length} queries</span></summary>
          <p className="figure-note">{result.source === "live" ? "Queries executed for this search, grouped by relationship. Row totals may include duplicates." : "This search used a cached graph and has no live database query receipts."} FIXED_IN and SHORTCUT evidence comes from saved fix history.</p>
          {bounded > 0 && <p className="live-bounded">{bounded} {bounded === 1 ? "query reached its row limit" : "queries reached their row limits"}. Additional matching edges may exist beyond this search.</p>}
          {[...receiptGroups].map(([relation, entries]) => {
            const rows = entries.reduce((total, { query }) => total + query.rows, 0);
            const limited = entries.filter(({ query }) => query.limit_reached).length;
            const label = relation === "Graph query" && entries.every(({ query }) => query.cypher.includes("RETURN n.id AS id, n.uid AS uid")) ? "Function identity lookup" : relation;
            return <details className="live-query-card live-query-group" key={relation}>
              <summary><span><b>{label}</b><small>{entries.length} {entries.length === 1 ? "query" : "queries"}</small></span><span>{rows.toLocaleString()} rows returned<small>{limited ? `${limited} at row limit` : "All within row limits"}</small></span></summary>
              <div className="live-query-group-entries">{entries.map(({ query, index }) => <details className="live-query-card" key={index}>
                <summary><span>Query {index + 1}</span><span>{query.rows.toLocaleString()} rows<small>{query.limit_reached ? "Row limit reached" : "Within row limit"}</small></span></summary>
                <pre>{query.cypher}</pre>
                <details className="live-query-params"><summary>Inspect query parameters{Array.isArray(query.params.seeds) ? ` (${query.params.seeds.length} seed functions)` : ""}</summary><pre>{JSON.stringify(query.params, null, 2)}</pre></details>
              </details>)}</div>
            </details>;
          })}
          {!result.queries.length && <p>No live database queries were returned.</p>}
        </details>
      </>}
    </div></div>
    <p className="figure-note">Have a confirmed fix? <a href="/app/connect#confirmed-fix">Teach your local agent from the diff →</a> Public search is read-only.</p>
  </section>;
}
