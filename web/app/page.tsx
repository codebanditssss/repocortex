import Link from "next/link";
import { Hero } from "@/components/landing/hero";
import { Replay } from "@/components/landing/replay";
import { ProvenanceReceipt } from "@/components/landing/provenance-receipt";
import { selectHeroIssue } from "@/lib/landing";
import type { CurveData, ProvenanceData } from "@/lib/data";
import evaluationJson from "@/public/data/curve.json";
import provenanceJson from "@/public/data/provenance.json";
import agent from "@/public/data/agent.json";
import hosted from "@/public/data/hosted-search.json";
import "./landing.css";

const evaluation = evaluationJson as CurveData;
const provenance = provenanceJson as ProvenanceData;

export default function Home() {
  const ticket = selectHeroIssue(provenance);
  return (
    <div className="landing">
      <header className="landing-head">
        <Link className="mark" href="/" aria-label="RepoCortex home">Repo<i>Cortex</i></Link>
        <span className="running-note">A field manual for a codebase that learns.</span>
        <nav aria-label="Main navigation">
          <Link href="/app">Results <span aria-hidden="true">→</span></Link>
          <a href="#install">Setup <span aria-hidden="true">↓</span></a>
          <a href="https://github.com/codebanditssss/repocortex" target="_blank" rel="noreferrer" aria-label="RepoCortex on GitHub (opens in a new tab)">GitHub <span aria-hidden="true">↗</span></a>
        </nav>
      </header>

      <main id="main-content" tabIndex={-1}>
        <Hero ticket={ticket} evaluation={evaluation} />
        <Replay evaluation={evaluation} />

        <section id="provenance" className="landing-section evidence-section" aria-labelledby="evidence-title">
          <header className="section-heading">
            <p className="sc section-index">02 / The evidence</p>
            <h2 id="evidence-title">Follow the result.</h2>
            <p className="section-dek">Each candidate has a route through the code graph. Inspect a recorded path, the agent study, or the hosted search check.</p>
          </header>
          <div className="evidence-list">
            <details className="evidence-disclosure">
              <summary><span>Why this function?</span><span className="evidence-value">Issue #{ticket.ticket}</span></summary>
              <div className="evidence-body">
                <p>A past issue and its learned FIXED_IN link lead to the candidate. This is a captured replay result.</p>
                <ProvenanceReceipt ticket={ticket} />
                <p className="figure-caption">Similarity, edge weight, and ranking score are distinct values. Across {provenance.holdout} held-out fix rows, {provenance.hits_with_fixed_in} hits used FIXED_IN paths and {provenance.hits_with_shortcut} used SHORTCUT paths; these are hit counts, not accuracy.</p>
                <Link className="text-link" href="/app/locate">Inspect search results →</Link>
              </div>
            </details>
            <div className="evidence-study">
              <details className="evidence-disclosure">
                <summary><span>Agent input tokens</span><span className="evidence-value">{agent.savings.with_input_tokens_pct}% fewer</span></summary>
                <div className="evidence-body">
                  <p>{agent.without.tokens.toLocaleString("en-US")} → {agent.with.tokens.toLocaleString("en-US")} mean input tokens per issue. Asking the agent to call the tool first reduced input tokens by {agent.savings.first_input_tokens_pct}%.</p>
                  <p>Measured with {agent.model}. One run per condition; input totals include cached reads. This study measures investigation, not successfully completed fixes.</p>
                  <Link className="text-link" href="/app/agent">Read the agent study →</Link>
                </div>
              </details>
              <p className="evidence-caveat">{agent.n} Django tasks. Top-1 correctness: 13/30 with the tool, 12/30 without. No established correctness gain.</p>
            </div>
            <div className="evidence-study">
              <details className="evidence-disclosure">
                <summary><span>Hosted search check</span><span className="evidence-value">{hosted.valid_live_responses}/{hosted.requests} passed</span></summary>
                <div className="evidence-body">
                  <p>Four concurrent requests against the hosted app, with live HydraDB traversal. Median response {hosted.p50_seconds.toFixed(2)} s; p95 {hosted.p95_seconds.toFixed(2)} s, including network and queueing.</p>
                  <Link className="text-link" href="/app/load">Inspect the request results →</Link>
                </div>
              </details>
              <p className="evidence-caveat">Four repeated reports. A small read-only smoke check, not sustained capacity, cold-start, or learning-write load.</p>
            </div>
          </div>
        </section>
      </main>

      <footer id="install" className="install-section">
        <p className="sc section-index">03 / Setup</p>
        <div className="install-grid">
          <div><h2>Pilot it on<br /><i>one repository.</i></h2>
            <p className="section-dek">Compare the same agent and budget with and without RepoCortex on preselected bugs. Adopt it only if the measured result justifies the setup.</p></div>
          <div className="install-command">
            <p className="install-context">HydraDB stores the graph and confirmed-fix journal. Setup requires Python, the runtime files, and a running graph database.</p>
            <Link className="landing-primary" href="/app/connect">Connect your agent <span aria-hidden="true">→</span></Link>
            <a className="text-link" href="https://github.com/codebanditssss/repocortex/blob/main/docs/maintainer-pilot.md" target="_blank" rel="noreferrer">Run a measured pilot <span aria-hidden="true">↗</span></a>
            <p className="news source-note">The hosted app is read-only. The setup guide includes checks for local search and feedback.</p>
          </div>
        </div>
        <div className="landing-colophon"><Link className="mark" href="/">Repo<i>Cortex</i></Link><p className="news">Built on HydraDB. Measured on {evaluation.holdout} held-out Django fix rows.</p><a href="#main-content">Back to top ↑</a></div>
      </footer>
    </div>
  );
}
