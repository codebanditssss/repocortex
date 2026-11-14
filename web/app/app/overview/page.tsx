import type { Metadata } from "next";
import Link from "next/link";
import { PlateHeading } from "@/components/dashboard/plate-heading";
import { EvaluationTable } from "@/components/dashboard/evaluation-table";
import { GraphPlate } from "@/components/landing/graph-plate";
import { MetricChart } from "@/components/metric-chart";
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
          <p>Predict where a bug lives. See the real fix. Rewire the graph. RepoCortex learned from {evaluation.train} Django fixes in time order, then tested against the same {evaluation.holdout} held-out issues at every checkpoint.</p>
        </PlateHeading>
        <dl className="journal-metrics">
          <div><dt>Right file, first result</dt><dd>{formatPercent(end["file_acc@1"])}<small>from {formatPercent(start["file_acc@1"])} at step 0</small></dd></div>
          <div><dt>Right function, top 10</dt><dd>{formatPercent(end["function_acc@10"])}<small>from {formatPercent(start["function_acc@10"])} at step 0</small></dd></div>
          <div><dt>File lift over dense</dt><dd>+{Number(((end["file_acc@1"] - evaluation.baselines.dense["file_acc@1"]) * 100).toFixed(2))}<em> pp</em><small>dense: {formatPercent(evaluation.baselines.dense["file_acc@1"])}</small></dd></div>
          <div><dt>File lift over frozen</dt><dd>+{Number(((end["file_acc@1"] - evaluation.baselines.frozen["file_acc@1"]) * 100).toFixed(2))}<em> pp</em><small>frozen: {formatPercent(evaluation.baselines.frozen["file_acc@1"])}</small></dd></div>
        </dl>
        <section className="operator-ledger" aria-labelledby="operators-title">
          <div className="section-rule"><h2 id="operators-title">Amendments to the graph</h2><span className="cap">Totals across the training pass</span></div>
          <table className="manual-table operator-table"><caption className="sr-only">Measured operator counts</caption><thead className="sr-only"><tr><th scope="col">Operator</th><th scope="col">What changes</th><th scope="col">Count</th></tr></thead><tbody>
            <tr><th scope="row">Reweight</th><td>Strengthen useful paths; weaken misleading ones.</td><td>{evaluation.operators.edge_reweight}</td></tr>
            <tr><th scope="row">Path compression</th><td>A direct road for a repeated detour.</td><td>{evaluation.operators.path_compression}</td></tr>
            <tr><th scope="row">Gap ingestion</th><td>Bring missing code into reach.</td><td>{evaluation.operators.gap_ingestion}</td></tr>
            <tr><th scope="row">Merge / split</th><td>Resolve shared names and separate meanings.</td><td>{evaluation.operators.entity_merge_split}</td></tr>
          </tbody></table>
        </section>
        <details className="baseline-summary">
          <summary>All baselines, including BM25: {formatPercent(evaluation.baselines.bm25["file_acc@1"])} file / {formatPercent(evaluation.baselines.bm25["function_acc@10"])} function</summary>
          <table className="manual-table"><caption>At the end of the pass / held-out accuracy</caption><thead><tr><th scope="col">Method</th><th scope="col">File Acc@1</th><th scope="col">Function Acc@10</th></tr></thead><tbody>
            <tr><th scope="row">RepoCortex</th><td>{formatPercent(end["file_acc@1"])}</td><td>{formatPercent(end["function_acc@10"])}</td></tr>
            {(["dense", "frozen", "bm25"] as const).map((key) => <tr key={key}><th scope="row">{key === "bm25" ? "BM25" : key === "dense" ? "Dense vectors" : "Frozen graph"}</th><td>{formatPercent(evaluation.baselines[key]["file_acc@1"])}</td><td>{formatPercent(evaluation.baselines[key]["function_acc@10"])}</td></tr>)}
          </tbody></table>
        </details>
      </section>
      <aside className="overview-figures" aria-label="Repository and evaluation figures">
        <div className="figure-top"><p className="cap"><b>FIG. 1</b> A repository, connected.</p><Link className="btn" href="/app/replay">Replay history <kbd>R</kbd></Link></div>
        <figure className="overview-graph"><div className="graph-stage"><GraphPlate step={evaluation.train} modules /></div><figcaption className="cap">{stats.local_nodes.toLocaleString("en-US")} nodes, {stats.local_edges.toLocaleString("en-US")} edges in the scoped graph. Counts are real. The layout and vermilion reweights are placeholders.</figcaption></figure>
        <figure className="overview-curve"><figcaption className="cap"><b>FIG. 2</b> File Acc@1 as the graph learns.</figcaption><div className="manual-chart-scroll" tabIndex={0} role="region" aria-label="Overview held-out accuracy chart"><MetricChart data={evaluation} metric="file_acc@1" index={evaluation.curve.length - 1} /></div><p className="figure-note">{`All ${evaluation.curve.length} points are held-out evaluations. Rules show single-point baselines, not additional replay runs.`}</p></figure>
        <EvaluationTable data={evaluation} metric="file_acc@1" />
        <p className="figure-note">Scope: {evaluation.scope.join(" · ")}. The frozen reference is this pass&apos;s step 0 graph, with learning off. Learning gain is measured from that starting point.</p>
      </aside>
    </div>
  );
}
