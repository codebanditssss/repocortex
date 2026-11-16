import type { Metadata } from "next";
import Link from "next/link";
import { PlateHeading } from "@/components/dashboard/plate-heading";
import { EvaluationTable } from "@/components/dashboard/evaluation-table";
import { GraphPlate } from "@/components/landing/graph-plate";
import { MetricChart } from "@/components/metric-chart";
import lexical from "@/public/data/lexical_gap.json";
import { EvaluationNote } from "@/components/evaluation-note";
import evaluationJson from "@/public/data/curve.json";
import type { CurveData } from "@/lib/data";
import stats from "@/public/data/graph_stats.json";
import { formatPercent } from "@/lib/format";

export const metadata: Metadata = { title: "Overview" };
const evaluation = evaluationJson as CurveData;

export default function Overview() {
  const start = evaluation.curve[0];
  const end = evaluation.curve[evaluation.curve.length - 1];

  return (
    <div className="manual-page overview-layout">
      <section className="overview-copy">
        <PlateHeading chapter="overview" title={<>A record of<br /><i>what it learns.</i></>}>
          <p>Find the function behind a bug report. Measured on {evaluation.holdout} held-out Django fixes after learning from {evaluation.train} earlier fixes.</p>
        </PlateHeading>
        <div className="overview-actions"><Link className="btn" href="/app/locate">Find a function <span aria-hidden="true">→</span></Link><Link className="text-control" href="/app/replay">Explore the learning curve</Link></div>
        <dl className="journal-metrics overview-key-metrics">
          <div><dt>Right file, first result</dt><dd>{formatPercent(end["file_acc@1"])}<small>from {formatPercent(start["file_acc@1"])} at step 0</small></dd></div>
          <div><dt>Right function, top 10</dt><dd>{formatPercent(end["function_acc@10"])}<small>from {formatPercent(start["function_acc@10"])} at step 0</small></dd></div>
        </dl>
        <section className="feedback-proof" aria-labelledby="feedback-proof-title">
          <div className="section-rule"><h2 id="feedback-proof-title">One fix, <i>remembered.</i></h2><span className="cap">HydraDB feedback journal</span></div>
          <p>A reviewed fix for Django #37442 changed the confirmed function&apos;s rank, then a fresh process reconstructed the same learned result from HydraDB.</p>
          <dl className="journal-metrics feedback-proof-steps">
            <div><dt>Before feedback</dt><dd>02<small>Deserializer.__init__</small></dd></div>
            <div><dt>After feedback</dt><dd>01<small>one journal event written</small></dd></div>
            <div><dt>After restart</dt><dd>01<small>one event replayed</small></dd></div>
          </dl>
          <p className="figure-note">This verifies a durable update on the same report, not accuracy on unseen bugs. The base runtime hashes and graph counts stayed unchanged. <a href="https://github.com/codebanditssss/repocortex/blob/main/results/real_feedback_persistence.json" target="_blank" rel="noreferrer">Inspect the raw receipt →</a></p>
        </section>
        <details className="dashboard-disclosure operator-ledger"><summary>What changed in the graph</summary>
        <section aria-labelledby="operators-title">
          <div className="section-rule"><h2 id="operators-title">Amendments to the graph</h2><span className="cap">Totals across the training pass</span></div>
          <table className="manual-table operator-table"><caption className="sr-only">Measured operator counts</caption><thead className="sr-only"><tr><th scope="col">Operator</th><th scope="col">What changes</th><th scope="col">Count</th></tr></thead><tbody>
            <tr><th scope="row">Reweight</th><td>Strengthen useful paths; weaken misleading ones.</td><td>{evaluation.operators.edge_reweight}</td></tr>
            <tr><th scope="row">Path compression</th><td>A direct road for a repeated detour.</td><td>{evaluation.operators.path_compression}</td></tr>
            <tr><th scope="row">Gap ingestion</th><td>Bring missing code into reach.</td><td>{evaluation.operators.gap_ingestion}</td></tr>
            <tr><th scope="row">Merge / split</th><td>Resolve shared names and separate meanings.</td><td>{evaluation.operators.entity_merge_split}</td></tr>
          </tbody></table>
        </section></details>
        <EvaluationNote />
        <details className="dashboard-disclosure">
          <summary>Does learning work beyond Django?</summary>
          <p>With unchanged ranking settings, HTTPX improves from 14/33 successful held-out reports with the frozen graph to 15/33 after learning, following 51 training reports. Flask stays at 4/7 after 13 training reports.</p>
          <p>Two further datasets were frozen before scoring. Click uses 44 training reports and 37 held out: text-only search finds 18/37, while frozen and learned graphs both find 21/37. Werkzeug uses 26 training reports and 16 held out: text-only finds 9/16, frozen finds 8/16, and learned finds 9/16.</p>
          <p>Graph structure helps Click at top ten, but learning adds no further successes and lowers MRR. Werkzeug recovers one report through learning without beating text-only search. The learning-gain intervals include zero. These retrospective offline checks do not establish reliable generalization.</p>
          <p><a href="https://github.com/codebanditssss/repocortex/blob/main/results/repository_ablations.md" target="_blank" rel="noreferrer">Read all four repository checks and memory controls →</a></p>
        </details>
        <section className="dashboard-disclosure" aria-labelledby="starlette-confirmation-title">
          <div className="section-rule"><h2 id="starlette-confirmation-title">Prospective Starlette confirmation</h2><span className="cap">Preregistered before scoring</span></div>
          <p>The fixed study learned from 41 chronological reports, then evaluated the same 24 untouched holdout reports at every checkpoint.</p>
          <p>On the training stream, flat fix memory found 31.7% and the learned graph found 34.1%&mdash;a directional secondary result. The registered holdout comparison tied at 54.2%, so this study demonstrated no learning advantage.</p>
          <p><a href="https://github.com/codebanditssss/repocortex/blob/main/results/starlette_prequential.md" target="_blank" rel="noreferrer">Study summary →</a> · <a href="https://github.com/codebanditssss/repocortex/blob/main/results/starlette_prequential_result.json" target="_blank" rel="noreferrer">Raw result →</a></p>
        </section>
        <details className="baseline-summary">
          <summary>All baselines, including dense + BM25 without graph</summary>
          <table className="manual-table"><caption>At the end of the pass / held-out accuracy</caption><thead><tr><th scope="col">Method</th><th scope="col">File Acc@1</th><th scope="col">Function Acc@10</th></tr></thead><tbody>
            <tr><th scope="row">RepoCortex</th><td>{formatPercent(end["file_acc@1"])}</td><td>{formatPercent(end["function_acc@10"])}</td></tr>
            <tr><th scope="row">Dense + BM25 (no graph)</th><td>{formatPercent(lexical.dense_bm25["file_acc@1"])}</td><td>{formatPercent(lexical.dense_bm25["function_acc@10"])}</td></tr>
            {(["dense", "frozen", "bm25"] as const).map((key) => <tr key={key}><th scope="row">{key === "bm25" ? "BM25" : key === "dense" ? "Dense vectors" : "Frozen graph"}</th><td>{formatPercent(evaluation.baselines[key]["file_acc@1"])}</td><td>{formatPercent(evaluation.baselines[key]["function_acc@10"])}</td></tr>)}
          </tbody></table>
        </details>
      </section>
      <aside className="overview-figures" aria-label="Repository and evaluation figures">
        <div className="section-rule"><h2>Learning on held-out fixes</h2><span className="cap">Recorded evaluation</span></div>
        <figure className="overview-curve"><figcaption className="cap">File accuracy at the first result.</figcaption><div className="manual-chart-scroll" tabIndex={0} role="region" aria-label="Overview held-out accuracy chart"><MetricChart data={evaluation} metric="file_acc@1" index={evaluation.curve.length - 1} /></div><p className="figure-note">{`All ${evaluation.curve.length} points are held-out evaluations. Rules show single-point baselines, not additional replay runs.`}</p></figure>
        <EvaluationTable data={evaluation} metric="file_acc@1" />
        <details className="dashboard-disclosure"><summary>Explore the repository graph</summary>
        <figure className="overview-graph"><div className="graph-stage"><GraphPlate step={evaluation.train} modules /></div><figcaption className="cap">{stats.local_nodes.toLocaleString("en-US")} nodes, {stats.local_edges.toLocaleString("en-US")} edges in the scoped graph. Counts are real. The layout and vermilion reweights are placeholders.</figcaption></figure>
        </details>
        <p className="figure-note">Scope: {evaluation.scope.join(" · ")}. The frozen reference is this pass&apos;s step 0 graph, with learning off. Learning gain is measured from that starting point.</p>
      </aside>
    </div>
  );
}
