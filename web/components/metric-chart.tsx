"use client";

import { useId } from "react";
import type { CurveData } from "@/lib/data";
import { formatPercent } from "@/lib/format";
import { chartFrame, chartModel, chartSeries, metricLabels, type LandingMetric } from "@/lib/landing";
export { metricLabels } from "@/lib/landing";

export function MetricChart({ data, metric, index, step, onSeek, wide = false }: {
  data: CurveData;
  metric: LandingMetric;
  index: number;
  step?: number;
  onSeek?: (step: number) => void;
  wide?: boolean;
}) {
  const id = useId();
  const frame = wide ? { left: 58, right: 820, top: 40, bottom: 336, width: 1004, height: 414 } : chartFrame;
  const { x, y, ticks } = chartModel(data, metric, frame);
  const point = data.curve[index];
  const path = (points: typeof data.curve) => points.map((value, i) => `${i ? "L" : "M"}${x(value.step).toFixed(2)},${y(value[metric]).toFixed(2)}`).join(" ");
  const lines = chartSeries(data, metric, index, frame);

  return (
    <svg className="metric-chart" viewBox={`0 0 ${frame.width} ${frame.height}`} role="img" aria-labelledby={`${id}-title ${id}-desc`} onClick={onSeek ? (event) => {
      const matrix = event.currentTarget.getScreenCTM();
      if (!matrix) return;
      const cursor = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
      onSeek(Math.round(Math.max(0, Math.min(1, (cursor.x - frame.left) / (frame.right - frame.left))) * data.train));
    } : undefined}>
      <title id={`${id}-title`}>{`Held-out ${metricLabels[metric]} through ${point.step} learned fixes`}</title>
      <desc id={`${id}-desc`}>{`RepoCortex: ${formatPercent(point[metric])}. Frozen graph: ${formatPercent(data.baselines.frozen[metric])}. Dense vectors: ${formatPercent(data.baselines.dense[metric])}. BM25: ${formatPercent(data.baselines.bm25[metric])}. Baselines are single-point references, not replay curves. The complete data table follows the controls.`}</desc>
      <text className="chart-axis-title" x={frame.left} y="17">{metricLabels[metric]} / held-out fixes (%)</text>
      {ticks.map((tick) => (
        <g key={tick}>
          <line className="chart-rule" x1={frame.left} x2={frame.right} y1={y(tick)} y2={y(tick)} />
          <text className="chart-tick" x={frame.left - 13} y={y(tick) + 4} textAnchor="end">{Math.round(tick * 100)}</text>
        </g>
      ))}
      {lines.filter((line) => line.id !== "repo").map((line) => (
        <line key={line.id} x1={frame.left} x2={frame.right} y1={y(line.value)} y2={y(line.value)} stroke={line.stroke} strokeWidth="1" strokeDasharray={line.dash} />
      ))}
      <path d={path(data.curve)} className="chart-future" />
      <path d={path(data.curve.slice(0, index + 1))} className="chart-learned" />
      {data.curve.map((value, i) => <circle key={value.step} cx={x(value.step)} cy={y(value[metric])} r={i <= index ? 2.8 : 2} fill={i <= index ? "var(--red)" : "var(--paper)"} stroke={i <= index ? "var(--red)" : "var(--ink3)"}><title>{`${value.step} fixes: ${formatPercent(value[metric])}`}</title></circle>)}
      <line className="chart-playhead" x1={x(step ?? point.step)} x2={x(step ?? point.step)} y1={frame.top} y2={frame.bottom} />
      <circle cx={x(point.step)} cy={y(point[metric])} r="5" fill="var(--red)" stroke="var(--paper)" strokeWidth="2" />
      {lines.map((line) => (
        <g key={line.id} className={line.id === "repo" ? "chart-label-repo" : "chart-label-baseline"}>
          <path d={`M${frame.right + 9},${y(line.value)} L${frame.right + 20},${line.labelY} H${frame.right + 27}`} fill="none" stroke={line.stroke} strokeWidth=".7" />
          <text className="chart-series-label" x={frame.right + 35} y={line.labelY - 3}>{line.label}</text>
          <text className="chart-series-value" x={frame.right + 35} y={line.labelY + 24}>{formatPercent(line.value)}</text>
        </g>
      ))}
      <line x1={frame.left} x2={frame.right} y1={frame.bottom} y2={frame.bottom} stroke="var(--ink)" />
      {data.curve.filter((_, i) => i % 2 === 0 || i === data.curve.length - 1).map((value) => (
        <g key={value.step}><line x1={x(value.step)} x2={x(value.step)} y1={frame.bottom} y2={frame.bottom + 6} stroke="var(--ink2)" /><text className="chart-tick" x={x(value.step)} y={frame.bottom + 23} textAnchor="middle">{value.step}</text></g>
      ))}
      <text className="chart-axis-title chart-x-title" x={frame.left} y={frame.bottom + 57}>Merged fixes learned, in time order</text>
    </svg>
  );
}
