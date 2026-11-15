"use client";

import { EvaluationNote } from "@/components/evaluation-note";
import { useEffect, useRef, useState } from "react";
import type { CurveData } from "@/lib/data";
import { formatPercent } from "@/lib/format";
import { type LandingMetric } from "@/lib/landing";
import { MetricChart, metricLabels } from "@/components/metric-chart";
import { GraphPlate } from "./graph-plate";
import { PlateImage } from "@/components/plate-image";
import { useInView, usePageVisible } from "./use-field-state";

export function Replay({ evaluation: data }: { evaluation: CurveData }) {
  const [index, setIndex] = useState(data.curve.length - 1);
  const [metric, setMetric] = useState<LandingMetric>("file_acc@1");
  const [playing, setPlaying] = useState(false);
  const [numbers, setNumbers] = useState(false);
  const ref = useRef<HTMLElement>(null);
  const visible = useInView(ref);
  const pageVisible = usePageVisible();
  const point = data.curve[index];
  const first = data.curve[0];
  const last = data.curve[data.curve.length - 1];

  useEffect(() => {
    if (!playing || !visible || !pageVisible) return;
    const timer = setTimeout(() => {
      if (index < data.curve.length - 1) setIndex(index + 1);
      else setPlaying(false);
    }, 900);
    return () => clearTimeout(timer);
  }, [playing, visible, pageVisible, index, data.curve.length]);

  return (
    <section id="replay" className="landing-section replay-section" ref={ref} aria-labelledby="replay-title">
      <div className="replay-intro">
        <div className="section-heading"><p className="sc section-index"><span className="num">02</span> / The learning pass</p><h2 id="replay-title">Replay.</h2></div>
        <p className="section-dek">Predict. See the real fix. Learn.<br />Then ask the same questions again.</p>
        <p className="news source-note">{data.train} fixes learned in time order. The same {data.holdout} held-out fixes scored at every checkpoint. Three test rows share tickets with training; this is a retrospective replay on a fixed code snapshot.</p>
      </div>
      <PlateImage className="section-ornament" src="/art/doodle-shortcut.webp" alt="A wandering ink path takes a short vermilion connection between two points." marginalia />
      <div className="replay-instrument">
        <figure className="replay-graph">
          <figcaption><span className="sc">The graph, reweighted</span><span className="fixture-label sc">Placeholder layout &amp; deltas</span></figcaption>
          <div className="replay-graph-stage"><GraphPlate step={point.step} /><div className="replay-step"><span className="num">{String(point.step).padStart(3, "0")}</span><span className="news">/ {data.train} fixes learned</span></div></div>
          <p className="figure-caption">Vermilion marks strengthened edges. Layout and weight changes illustrate the mechanism, not a captured mutation log. No shortcuts, gap fills, or merges are shown.</p>
        </figure>
        <figure className="replay-chart-figure">
          <figcaption className="chart-heading"><span className="sc">Fig. 2 / Held-out evaluation</span><span className="sc measured-label">Measured</span></figcaption>
          <div className="metric-switch" role="group" aria-label="Evaluation metric">
            {(Object.keys(metricLabels) as LandingMetric[]).map((value) => <button key={value} type="button" aria-pressed={metric === value} onClick={() => setMetric(value)}>{metricLabels[value]}</button>)}
          </div>
          <div className="chart-scroll" role="region" tabIndex={0} aria-label="Evaluation chart, scroll horizontally on small screens"><MetricChart data={data} metric={metric} index={index} /></div>
          <p className="figure-caption">File Acc@1 rises from {formatPercent(first["file_acc@1"])} to {formatPercent(last["file_acc@1"])}. Function Acc@10 rises from {formatPercent(first["function_acc@10"])} to {formatPercent(last["function_acc@10"])}. The learned graph beats dense on both. MRR ends at {last.mrr.toFixed(3)}. Lines connect measured checkpoints, including the dips; baselines are horizontal references.</p>
        </figure>
      </div>
      <div className="replay-controls">
        <button className="replay-play" type="button" aria-label={playing ? "Pause learning replay" : "Play learning replay"} aria-pressed={playing} onClick={() => {
          if (playing) setPlaying(false);
          else { if (index === data.curve.length - 1) setIndex(0); setPlaying(true); }
        }} >{playing ? "Pause" : "Play"} <span aria-hidden="true">{playing ? "Ⅱ" : "▷"}</span></button>
        <div className="replay-range"><label htmlFor="replay-step"><span className="sc">Scrub the learning pass</span><output htmlFor="replay-step" className="num">{point.step} / {data.train}</output></label><input id="replay-step" type="range" min="0" max={data.curve.length - 1} step="1" value={index} aria-valuetext={`${point.step} merged fixes learned. ${metricLabels[metric]}: ${formatPercent(point[metric])}`} onChange={(event) => { setPlaying(false); setIndex(Number(event.target.value)); }} /><div className="range-ends num"><span>{first.step}</span><span>{last.step} fixes</span></div></div>
        <button className="show-numbers" type="button" aria-expanded={numbers} aria-controls="curve-data" onClick={() => setNumbers(!numbers)}>{numbers ? "Hide" : "Show"} the numbers <span aria-hidden="true">{numbers ? "−" : "+"}</span></button>
      </div>
      <div className="operator-notes">
        <article><h3><span className="num">01</span> Reweight <span className="num operator-count">{data.operators.edge_reweight.toLocaleString("en-US")}</span></h3><p>Paths that led to the real fix get stronger. Paths that misled it fade.</p><small className="sc">Ran in this pass</small></article>
        <article><h3><span className="num">02</span> Path compression <span className="num operator-count">{data.operators.path_compression}</span></h3><p>A direct road for a repeated detour.</p><small className="sc">Ran in this pass</small></article>
        <article><h3><span className="num">03</span> Gap ingestion <span className="num operator-count">{data.operators.gap_ingestion}</span></h3><p>A missing link, added when it cannot reach the fix.</p><small className="sc">Ran in this pass</small></article>
        <article><h3><span className="num">04</span> Merge / split <span className="num operator-count">{data.operators.entity_merge_split}</span></h3><p>Resolve shared names and divided meanings.</p><small className="sc">Ran in this pass</small></article>
      </div>
      <div id="curve-data" className={numbers ? "curve-tables" : "sr-only"}>
        {(Object.keys(metricLabels) as LandingMetric[]).map((value) => (
          <div className="curve-table-scroll" key={value} tabIndex={numbers ? 0 : undefined} role="region" aria-label={`${metricLabels[value]} data table`}><table><caption>{metricLabels[value]} / same {data.holdout} held-out fixes at every checkpoint</caption><thead><tr><th scope="col">Fixes learned</th><th scope="col">RepoCortex</th><th scope="col">Frozen</th><th scope="col">Dense</th><th scope="col">BM25</th></tr></thead><tbody>{data.curve.map((row) => <tr key={row.step}><th scope="row">{row.step}</th><td>{formatPercent(row[value])}</td><td>{formatPercent(data.baselines.frozen[value])}</td><td>{formatPercent(data.baselines.dense[value])}</td><td>{formatPercent(data.baselines.bm25[value])}</td></tr>)}</tbody></table></div>
        ))}
      </div>
      <details className="replay-params"><summary className="sc">Ranker parameters / this pass</summary><dl>{Object.entries(data.params).map(([name, value]) => <div key={name}><dt className="num">{name}</dt><dd className="num">{value}</dd></div>)}</dl><p className="news">The frozen reference is this pass&apos;s step 0 graph, with learning off. Learning gain is measured from that starting point.</p></details>
      <EvaluationNote />
      <p className="replay-endnote news">A measured gain on {data.holdout} held-out fix rows. Not a claim about every codebase.</p>
    </section>
  );
}
