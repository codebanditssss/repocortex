"use client";

import { Fragment, useState } from "react";
import type { ProvenanceData, ProvenanceHit, ProvenanceIssue } from "@/lib/data";
import { functionName, pathKind, searchProvenance, shortFunctionName } from "@/lib/dashboard";
import { fixedInRoutes, selectHeroIssue } from "@/lib/landing";
import { ProvenanceReceipt } from "@/components/landing/provenance-receipt";
import { LiveLocate } from "./live-locate";
import { PlateHeading } from "./plate-heading";

function HitReceipt({ issue, hit }: { issue: ProvenanceIssue; hit: ProvenanceHit }) {
  const routes = fixedInRoutes(hit.path);
  return (
    <section className="hit-receipt" aria-label={`Provenance receipt for rank ${hit.rank}`}>
      <p className="sc">Provenance receipt / held-out #{issue.ticket}</p>
      {routes.map((route, index) => <div className="evidence-route" key={index}><div><span className="sc">Past issue</span><strong>#{route.ticket}</strong><small className="num">similarity {route.similarity}</small></div><span className="evidence-edge"><b>FIXED_IN</b><span aria-hidden="true">→</span><small className="num">w {route.weight}</small></span><div><span className="sc">Function</span><strong>{route.target.split(".").slice(-2).join(".")}</strong><small>Captured fix evidence</small></div></div>)}
      {(!routes.length || hit.path.includes("SHORTCUT")) && <ul className="readable-paths">{hit.path.split(" | ").filter((path) => !routes.length || path.includes("SHORTCUT")).map((path, index) => <li key={index}>{path.replaceAll("-SHORTCUT->", " → SHORTCUT → ")}</li>)}</ul>}
      <details className="receipt-source"><summary>Read the full receipt</summary><ProvenanceReceipt ticket={issue} hit={hit} /></details>
    </section>
  );
}

export function LocateScreen({ data }: { data: ProvenanceData }) {
  const demo = selectHeroIssue(data);
  const [query, setQuery] = useState(String(demo.ticket));
  const [submitted, setSubmitted] = useState(String(demo.ticket));
  const [matches, setMatches] = useState<ProvenanceIssue[]>([demo]);
  const [matchIndex, setMatchIndex] = useState(0);
  const [rank, setRank] = useState(1);
  const [searchCount, setSearchCount] = useState(0);
  const issue = matches[matchIndex];
  const samples = [demo, ...data.issues.filter((value) => value.ticket !== demo.ticket).slice(0, 2)];

  const search = (text: string) => {
    const results = searchProvenance(data, text);
    setQuery(text); setSubmitted(text.trim()); setMatches(results);
    setSearchCount((count) => count + 1);
    setMatchIndex(0); setRank(results[0]?.hits[0]?.rank ?? 1);
  };



  return (
    <div className="manual-page"><nav className="locate-modes" aria-label="Choose search mode"><a href="#fresh-search"><strong>Fresh report</strong><span>Rank functions for a new Django bug</span></a><a href="#saved-evidence"><strong>Saved evidence</strong><span>Browse 319 recorded predictions</span></a></nav><LiveLocate /><div id="saved-evidence" className="locate-layout" tabIndex={-1}>
      <section className="locate-composer" aria-label="Search held-out evidence">
        <PlateHeading chapter="locate" title={<>Where it <i>hurts.</i></>} />
        <form onSubmit={(event) => { event.preventDefault(); search(String(new FormData(event.currentTarget).get("query") ?? "")); }}>
          <div className="ticket-sheet"><div className="ticket-sheet-head"><label htmlFor="locate-query">Ticket, function, or filename</label><span>Saved evidence</span></div><textarea id="locate-query" name="query" value={query} placeholder="Try a ticket number or a function name" rows={4} aria-describedby="locate-search-help" onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); search(event.currentTarget.value); }
          }} /></div>
          <div className="locate-options"><span>repo <u>django</u></span><span>index <u>{data.holdout} issues</u></span><button className="btn" type="submit">Search saved <kbd>Enter</kbd></button></div>
        </form>
        <div className="saved-search-feedback" role="status" aria-live="polite" aria-atomic="true">
          <p key={searchCount}>{searchCount === 0
            ? `Example shown: ticket #${demo.ticket}. Enter another ticket, function, or filename to search.`
            : !submitted ? "Enter a ticket number, function, or filename."
            : matches.length ? `${matches.length} saved ${matches.length === 1 ? "record" : "records"} found for “${submitted}”. Results are shown in Ranked suspects.`
            : `No saved records match “${submitted}”. For a new bug report, use the live search above.`}</p>
        </div>
        <p id="locate-search-help" className="figure-note">Matches ticket numbers, functions and filenames—not bug-report text.</p>
        <div className="sample-tickets"><h2 className="sc">Or try a held-out ticket</h2>{samples.map((sample) => <button type="button" key={sample.ticket} onClick={() => search(String(sample.ticket))}><span className="num">#{sample.ticket}</span><span>{shortFunctionName(sample.hits[0])}</span></button>)}</div>
        <dl className="evidence-index"><div><dt>Held-out issues</dt><dd className="num">{data.holdout}</dd></div><div><dt>Hits using FIXED_IN</dt><dd className="num">{data.hits_with_fixed_in}</dd></div><div><dt>Hits using SHORTCUT</dt><dd className="num">{data.hits_with_shortcut}</dd></div></dl>
      </section>
      <section className="locate-results" aria-labelledby="locate-results-title">
        <div className="section-rule"><h2 id="locate-results-title">{issue ? <>Ranked <i>suspects</i></> : "The evidence index"}</h2><span className="cap" role="status">{issue ? `${issue.hits.length} captured hits · #${issue.ticket}` : submitted ? "No matches" : "No search yet"}</span></div>
        {matches.length > 1 && <div className="issue-picker"><label htmlFor="matched-ticket">{matches.length} matching records</label><select id="matched-ticket" value={matchIndex} onChange={(event) => { const index = Number(event.target.value); setMatchIndex(index); setRank(matches[index].hits[0]?.rank ?? 1); }}>{matches.map((match, index) => <option key={index} value={index}>#{match.ticket} / {shortFunctionName(match.hits[0])} / record {index + 1}</option>)}</select></div>}
        {issue ? <>
          <ol className="ranked-hits">{issue.hits.map((hit) => <Fragment key={hit.rank}><li>
            <button className={`ranked-hit${rank === hit.rank ? " is-selected" : ""}`} type="button" aria-expanded={rank === hit.rank} aria-controls={`hit-receipt-${hit.rank}`} onClick={() => setRank(rank === hit.rank ? 0 : hit.rank)}>
              <span className="hit-rank">{hit.rank}</span><span className="hit-function"><strong title={functionName(hit)}>{shortFunctionName(hit)}</strong><small>{hit.file}</small></span><span className="hit-via"><span>{pathKind(hit.path)}</span>{hit.gold && <small>Gold match</small>}</span><span className="hit-score num">{hit.score.toFixed(3)}<i style={{ width: `${Math.max(0, Math.min(1, hit.score)) * 100}%` }} /></span>
            </button>
            {rank === hit.rank && <div id={`hit-receipt-${hit.rank}`} className="expanded-hit"><HitReceipt issue={issue} hit={hit} /></div>}
          </li></Fragment>)}</ol>
          <aside className="locate-endnote"><span className="sc">What this proves</span><p>Recorded held-out predictions. Gold marks match the actual fix. FIXED_IN and SHORTCUT show learned evidence; <b>dense + bm25</b> shows text retrieval.</p></aside>
        </> : <div className="locate-empty"><h3>{submitted ? "Nothing in this index matches." : "Start with a ticket."}</h3><p>{submitted ? `No saved ticket, function, or filename matched “${submitted}”. Try a ticket number or a filename such as query.py.` : "Type a ticket number or filename, then press Search saved."}</p><button type="button" className="underlined-control" onClick={() => search(String(demo.ticket))}>Load example #{demo.ticket} →</button></div>}
      </section>
    </div></div>
  );
}
