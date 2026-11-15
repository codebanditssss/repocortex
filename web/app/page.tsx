import Link from "next/link";
import { Hero } from "@/components/landing/hero";
import { Replay } from "@/components/landing/replay";
import { CopyCommand } from "@/components/landing/copy-command";
import { ProvenanceReceipt } from "@/components/landing/provenance-receipt";
import { fixedInRoutes, hitSymbol, selectHeroIssue } from "@/lib/landing";
import type { CurveData, LoadTest, ProvenanceData } from "@/lib/data";
import evaluationJson from "@/public/data/curve.json";
import provenanceJson from "@/public/data/provenance.json";
import agent from "@/public/data/agent.json";
import loadJson from "@/public/data/loadtest.json";
import "./landing.css";

const number = (value: number) => value.toLocaleString("en-US");
const evaluation = evaluationJson as CurveData;
const provenance = provenanceJson as ProvenanceData;
const load = loadJson as LoadTest;

function FixtureLabel({ show = true }: { show?: boolean }) {
  return show ? <span className="fixture-label sc">Placeholder fixture</span> : null;
}

function SectionHead({ number: index, label, title }: {
  number: string; label: string; title: string;
}) {
  return (
    <header className="section-heading">
      <p className="sc section-index"><span className="num">{index}</span> / {label}</p>
      <h2>{title}</h2>
    </header>
  );
}

export default function Home() {
  const ticket = selectHeroIssue(provenance);
  const hit = ticket.hits.find((hit) => hit.gold)!;
  const route = fixedInRoutes(hit.path)[0];
  return (
    <div className="landing">
      <header className="landing-head">
        <Link className="mark" href="/" aria-label="RepoCortex home">Repo<i>Cortex</i></Link>
        <span className="running-note">A field manual for a codebase that learns.</span>
        <nav aria-label="Main navigation">
          <Link href="/app">Results <span aria-hidden="true">→</span></Link>
          <a href="#install">Setup <span aria-hidden="true">↓</span></a>
          <a href="https://github.com/codebanditssss/hydradb-hack" target="_blank" rel="noreferrer" aria-label="RepoCortex on GitHub (opens in a new tab)">GitHub <span aria-hidden="true">↗</span></a>
        </nav>
      </header>

      <main id="main-content" tabIndex={-1}>
        <Hero ticket={ticket} evaluation={evaluation} />

        <section className="landing-section similarity" aria-labelledby="similar-title">
          <header className="section-heading">
            <p className="sc section-index"><span className="num">01</span> / Retrieval</p>
            <h2 id="similar-title">Similar is not relevant.</h2>
          </header>
          <p className="section-dek">Close names are a starting point. For held-out issue #{ticket.ticket}, a learned link from a past fix brings the gold function to rank one.</p>
          <div className="comparison-ticket">
            <span className="sc">Held-out issue #{ticket.ticket}</span><p>{hitSymbol(hit)}</p><span className="sc measured-label">Measured</span>
          </div>
          <div className="retrieval-split">
            <figure className="vector-example">
              <figcaption><span className="sc">Nearby candidates</span><span className="news">Dense + BM25 paths</span></figcaption>
              <div className="chunk-stack" role="group" aria-label="Measured hybrid-search hits from the same ranked result">
                {ticket.hits.filter((candidate) => candidate.path === "dense + bm25").map((candidate) => (
                  <div className="search-chunk" key={candidate.uid}>
                    <span className="num">Rank {candidate.rank} / score {candidate.score}</span>
                    <p className="num">{hitSymbol(candidate).replace("django.db.models.query.", "")}</p>
                    <p>{candidate.file}</p>
                  </div>
                ))}
              </div>
              <p className="news comparison-note">Plausible neighbors, but none is the gold function for this issue. These are hits from the combined ranking, not a separate baseline run.</p>
            </figure>
            <figure className="graph-example">
              <figcaption><span className="sc">A route from a past fix</span><span className="news">Learned FIXED_IN path</span></figcaption>
              <ol className="function-route">
                <li><span className="num route-branch">┌</span><span>Issue #{ticket.ticket}<small className="sc">Chronological holdout</small></span></li>
                <li><span className="num route-branch">├</span><span>Issue #{route.ticket}<small className="sc">Past fix / similarity <span className="num">{route.similarity}</span></small></span></li>
                <li><span className="num route-branch">└</span><span>{hitSymbol(hit).replace("django.db.models.query.", "")}<small className="sc">FIXED_IN / weight <span className="num">{route.weight}</span></small></span></li>
              </ol>
              <p className="news comparison-note">{hit.file}. Rank {hit.rank}, score {hit.score}, and a match to the held-out gold function.</p>
            </figure>
          </div>
        </section>

        <Replay evaluation={evaluation} />

        <section id="provenance" className="landing-section provenance-section">
          <div>
            <SectionHead number="03" label="Provenance" title="Why it said that." />
            <p className="section-dek">The result carries its evidence: a past issue, a learned FIXED_IN link, and the function it reached.</p>
            <p className="news source-note">Across {provenance.holdout} held-out fix rows, {provenance.hits_with_fixed_in} hits used FIXED_IN paths and {provenance.hits_with_shortcut} used SHORTCUT paths. These are hit counts, not issue-level accuracy.</p>
          </div>
          <figure className="provenance-figure">
            <figcaption><span className="sc">Route receipt / issue #{ticket.ticket}</span><span className="sc measured-label">Measured</span></figcaption>
            <ProvenanceReceipt ticket={ticket} />
            <p className="figure-caption"><b>FIG. 3</b> Captured in {provenance.source}. Similarity, edge weight, and ranking score are distinct values, preserved from the measured record.</p>
          </figure>
        </section>

        <section className="landing-section agent-section">
          <div className="heading-row">
            <SectionHead number="04" label="Context" title="Your agent reads less." />
            <FixtureLabel show={agent.placeholder} />
          </div>
          <p className="section-dek">Same agent, same {agent.n} tickets. One of them asked the graph first.</p>
          <p className="news source-note">{agent.note}</p>
          <p className="terminal-ticket"><span className="sc">Ticket</span> {agent.ticket}</p>
          <div className="terminal-pair">
            {(["without", "with"] as const).map((mode) => (
              <figure className={`terminal terminal-${mode}`} key={mode}>
                <figcaption><span className="sc">{mode === "with" ? "With RepoCortex" : "Without RepoCortex"}</span><span className="num">measured run</span></figcaption>
                <div className="terminal-body num">
                  {mode === "without" ? (
                    <>
                      <p><span className="terminal-prompt">$</span> investigate ticket</p>
                      <p className="terminal-muted">› search_code x {agent.example.without.calls_by_tool.search_code}<br />› read_file x {agent.example.without.calls_by_tool.read_file}<br />› {agent.example.without.files_opened} files opened<br />› {agent.example.without.turns} turns, {number(agent.example.without.tokens_in)} input tokens</p>
                    </>
                  ) : (
                    <>
                      <p><span className="terminal-prompt">$</span> {agent.with.tool_calls[0].name}(&#123;</p>
                      <p className="terminal-muted indent">report: &quot;{agent.with.tool_calls[0].args.report}&quot;,<br />k: {agent.with.tool_calls[0].args.k}</p>
                      <p>&#125;)</p>
                      <p className="terminal-result">{agent.with.tool_calls[0].result_summary}</p>
                      <p className="terminal-muted">› {agent.example.with.turns} turns, {number(agent.example.with.tokens_in)} input tokens</p>
                    </>
                  )}
                </div>
                <dl className="terminal-stats">
                  <div><dt>Input tokens, mean</dt><dd className="num">{number(agent[mode].tokens)}</dd></div>
                  <div><dt>Turns</dt><dd className="num">{agent[mode].turns}</dd></div>
                  <div><dt>Files read</dt><dd className="num">{agent[mode].files_read}</dd></div>
                </dl>
              </figure>
            ))}
          </div>
          <p className="figure-caption"><b>FIG. 4</b> Traces are one measured run on {agent.ticket}. Totals are means over {agent.n} held-out fix rows with {agent.model}: {agent.savings.with_input_tokens_pct}% fewer input tokens with the tool, {agent.savings.first_input_tokens_pct}% when told to call it first.</p>
        </section>

        <section className="landing-section load-section">
          <div>
            <SectionHead number="05" label="Concurrency" title="Eight users. One measured run." />
            <p className="section-dek">{number(load.requests)} requests. {load.failures} failures.<br />Here&apos;s the field sheet.</p>
            <p className="news source-note">{load.tool}, {load.duration_s} seconds, spawn rate {load.spawn_rate} users/s, against the local {load.endpoint} endpoint. Saved phase-2 run on the smaller cached ranker, not live HydraDB traversal latency.</p>
          </div>
          <div className="load-field">
            <div className="load-table-head"><span className="sc">{load.endpoint} / latency in ms</span><span className="sc measured-label">Measured</span></div>
            <div className="load-table-scroll" tabIndex={0} role="region" aria-label="Measured Locust results">
            <table className="load-table">
              <caption className="sr-only">Single measured Locust run with eight concurrent users</caption>
              <thead><tr><th scope="col">Users</th><th scope="col">p50 <span>(ms)</span></th><th scope="col">p95 <span>(ms)</span></th><th scope="col">Failures</th><th scope="col">Req/s</th></tr></thead>
              <tbody><tr><th scope="row" className="num">{load.users}</th><td className="num">{load.median_ms}</td><td className="num">{load.p95_ms}</td><td className="num">{load.failures}</td><td className="num">{load.rps}</td></tr></tbody>
            </table>
            </div>
            <p className="figure-caption"><b>FIG. 5</b> Average {load.avg_ms} ms, min {load.min_ms} ms, max {load.max_ms} ms, p99 {load.p99_ms} ms. Source: {load.source}. No measurements at higher user counts are available.</p>
          </div>
        </section>

        <section className="landing-section hydra-section">
          <div>
            <SectionHead number="06" label="Storage" title="Built on HydraDB." />
            <p className="section-dek">The learning is ours.<br />The graph lives in HydraDB.</p>
            <a className="text-link" href="https://hydradb.com">Meet HydraDB <span aria-hidden="true">→</span></a>
          </div>
          <figure className="cypher-figure">
            <figcaption className="sc">A reweight, in Cypher-like notation / illustrative</figcaption>
            <pre tabIndex={0}><code><span>MATCH</span> (source)-[route:CALLS]-&gt;(target){"\n"}<span>WHERE</span> source.id = $source{"\n"}  <span>AND</span> target.id = $target{"\n"}<span>SET</span> route.weight = $learned_weight{"\n"}<span>RETURN</span> source, route, target;</code></pre>
            <p className="news source-note">Same codebase. Same ranker. The graph carries what it learned.</p>
          </figure>
        </section>
      </main>

      <footer id="install" className="install-section">
        <p className="sc section-index"><span className="num">07</span> / Take it with you</p>
        <div className="install-grid">
          <div><h2>Search with<br /><i>your agent.</i></h2>
            <p className="section-dek">Use local search from an MCP-compatible coding agent.</p></div>
          <div className="install-command">
            <p className="sc">Start read-only MCP search</p>
            <CopyCommand />
            <p className="news source-note">Requires the Python environment, runtime files and graph setup. HTTP: http://127.0.0.1:8766/mcp. For confirmed-fix feedback, use the local stdio setup below.</p>
            <Link className="landing-primary" href="/app">Explore the results <span aria-hidden="true">→</span></Link>
            <Link className="text-link" href="/app/connect">Connect your agent <span aria-hidden="true">→</span></Link>
          </div>
        </div>
        <div className="landing-colophon"><Link className="mark" href="/">Repo<i>Cortex</i></Link><p className="news">Measured on {evaluation.holdout} held-out Django fix rows. Fixtures marked where used.</p><a href="#main-content">Back to top ↑</a></div>
      </footer>
    </div>
  );
}
