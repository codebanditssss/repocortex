import type { CurveData } from "@/lib/data";
import { formatPercent } from "@/lib/format";
import { metricLabels } from "@/lib/landing";
import type { LandingMetric } from "@/lib/landing";

export function EvaluationTable({ data, metric, note }: { data: CurveData; metric: LandingMetric; note?: string }) {
  return (
    <details className="manual-data">
      <summary>Read the checkpoint data</summary>
      <div className="manual-table-scroll" role="region" aria-label={`${metricLabels[metric]} checkpoint data`} tabIndex={0}>
        <table className="manual-table">
          <caption>{metricLabels[metric]}, same {data.holdout} held-out issues at every checkpoint</caption>
          <thead><tr><th scope="col">Fixes learned</th><th scope="col">RepoCortex</th><th scope="col">Dense</th><th scope="col">Frozen</th><th scope="col">BM25</th></tr></thead>
          <tbody>{data.curve.map((point) => <tr key={point.step}><th scope="row">{point.step}</th><td>{formatPercent(point[metric])}</td><td>{formatPercent(data.baselines.dense[metric])}</td><td>{formatPercent(data.baselines.frozen[metric])}</td><td>{formatPercent(data.baselines.bm25[metric])}</td></tr>)}</tbody>
        </table>
      </div>
      {note && <p className="figure-note">{note}</p>}
    </details>
  );
}
