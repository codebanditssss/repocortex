"use client";

import { useEffect, useRef, useState } from "react";
import { isBackendStatus, isLocateResult, receiptRelation, shortLiveName, type BackendStatus, type LocateResult } from "@/lib/live";

const example = "QuerySet union loses ordering when combined with values_list. The SQL compiler raises an error when ordering by a column missing from the selected fields.";

export function LiveLocate() {
  const [report, setReport] = useState("");
  const [status, setStatus] = useState<BackendStatus | null>(null);
  const [result, setResult] = useState<LocateResult | null>(null);
  const [pending, setPending] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/status", { signal: controller.signal }).then((response) => response.json()).then((value) => {
      setStatus(isBackendStatus(value) ? value : { mode: "unavailable", connected: false });
    }).catch(() => { if (!controller.signal.aborted) setStatus({ mode: "unavailable", connected: false }); });
    return () => { controller.abort(); request.current?.abort(); };
  }, []);
  useEffect(() => {
    if (!pending) return;
    const started = Date.now();
    const interval = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(interval);
  }, [pending]);

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
      if (!controller.signal.aborted) setStatus({ mode: "unavailable", connected: false });
      setError(controller.signal.aborted ? "Search cancelled. Your report is still here." : failure instanceof Error && failure.name === "TimeoutError" ? "The search timed out. Please try again." : failure instanceof Error ? failure.message : "The search failed. Please try again.");
    } finally { setPending(false); request.current = null; }
  }

  const bounded = result?.queries.filter((query) => query.limit_reached).length ?? 0;
  return <section className="live-locate" aria-labelledby="live-locate-title">
    <div className="section-rule"><h2 id="live-locate-title">Follow a fresh <i>bug report.</i></h2><span className={`cap live-status${status?.connected ? " is-connected" : ""}`} role="status">{status === null ? "Checking service…" : status.connected ? "HydraDB connected" : status.mode === "replay" ? "Cached graph mode" : "Service offline"}</span></div>
    <div className="live-locate-grid"><form onSubmit={locate}>
      <div className="ticket-sheet"><div className="ticket-sheet-head"><label htmlFor="live-report">What is going wrong in Django?</label><span>Fresh search</span></div><textarea id="live-report" value={report} disabled={pending} onChange={(event) => setReport(event.target.value)} rows={5} maxLength={12000} required placeholder="Describe the error, expected behavior, and the code involved…" aria-describedby="live-search-help" /></div>
      <div className="locate-options"><span>repo <u>django</u></span><button className="btn" type="submit" disabled={pending || !report.trim()}>{pending ? "Tracing the graph…" : "Find functions →"}</button></div>
      <p id="live-search-help" className="figure-note">Search the recovered Django snapshot. Structural paths are queried in HydraDB when connected. Learned memory comes from the saved training run.</p>
      <button className="underlined-control" type="button" disabled={pending} onClick={() => setReport(example)}>Try a query compilation report →</button>
      <div className="live-method"><span className="sc">How to read a result</span><p>Start with the function, then open its evidence path. A ranking score compares candidates; it is not a probability that a function contains the bug.</p></div>
    </form><div className="live-search-results" aria-busy={pending}>
      {error && <div className="live-error" role="alert"><strong>Search paused</strong><p>{error}</p><span>Saved evidence below remains available.</span></div>}
      {pending && <div className="live-progress"><span className="sc" role="status">Searching · {elapsed}s elapsed</span><h3>Following the connections.</h3><p>Ranking candidates and collecting database query receipts. This can take several seconds.</p><button type="button" className="underlined-control" onClick={() => request.current?.abort()}>Cancel search</button></div>}
      {!result && !pending && !error && <div className="live-empty"><span className="sc">Report → functions → evidence</span><h3>A starting point for your next fix.</h3><p>Describe a bug to find functions worth investigating, with the graph evidence behind each suggestion.</p><div className="live-empty-steps"><span><b>01</b> Describe the failure</span><span><b>02</b> Inspect the suspects</span><span><b>03</b> Read the evidence</span></div></div>}
      {result && <><div className="live-result-heading"><h3>Functions to investigate</h3><span className="sc" role="status">{result.hits.length} candidates</span></div>
        <div className="live-provenance"><span>{result.source === "live" ? "Live structural graph" : "Cached structural graph"}</span><span>Cached learned memory</span></div>
        <ol className="ranked-hits live-ranked-hits">{result.hits.map((hit) => <li key={`${hit.rank}-${hit.uid}`}><details><summary><span className="hit-rank">{String(hit.rank).padStart(2, "0")}</span><span className="hit-function"><strong title={hit.qualname || hit.uid}>{shortLiveName(hit)}</strong><small>{hit.file}:{hit.line}</small></span><span className="live-score"><span className="num">{hit.score.toFixed(3)}</span><small>score</small></span><span className="live-expand" aria-hidden="true">+</span></summary><div className="live-hit-path"><span className="sc">Why this function surfaced</span><ul>{hit.path ? hit.path.split(" | ").map((path, index) => <li key={index}>{path}</li>) : <li>No graph path returned for this candidate.</li>}</ul><p className="figure-note">Learned FIXED_IN and SHORTCUT evidence can come from cached training memory. The database receipts below identify this search&apos;s live queries.</p><details className="live-function-id"><summary>Full function identifier</summary><code>{hit.uid}</code></details></div></details></li>)}</ol>
        {!result.hits.length && <p>No functions matched this report. Add an error message or relevant API name and try again.</p>}
        <details className="live-query-receipts"><summary><span>Database query receipts</span><span className="num">{result.queries.length} queries</span></summary><p className="figure-note">Each receipt records rows returned by a bounded query. Counts can overlap across queries; they are not unique function counts.</p>{bounded > 0 && <p className="live-bounded">{bounded} {bounded === 1 ? "query reached its row limit" : "queries reached their row limits"}. Additional matching edges may exist beyond this search.</p>}{result.queries.length ? result.queries.map((query, index) => <details className="live-query-card" key={index}><summary><span><b>{receiptRelation(query)}</b><small>Query {index + 1}</small></span><span>{query.rows.toLocaleString()} rows<small>{query.limit_reached ? "Row limit reached" : "Within row limit"}</small></span></summary><pre>{query.cypher}</pre><details className="live-query-params"><summary>Inspect query parameters{Array.isArray(query.params.seeds) ? ` (${query.params.seeds.length} seed functions)` : ""}</summary><pre>{JSON.stringify(query.params, null, 2)}</pre></details></details>) : <p>No live database queries were returned.</p>}</details>
      </>}
    </div></div>
  </section>;
}
