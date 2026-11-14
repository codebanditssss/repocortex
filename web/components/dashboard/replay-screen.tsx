"use client";

import { useCallback, useEffect, useState } from "react";
import type { CurveData } from "@/lib/data";
import { checkpointIndex, clampStep } from "@/lib/dashboard";
import { formatPercent } from "@/lib/format";
import type { LandingMetric } from "@/lib/landing";
import { MetricChart, metricLabels } from "@/components/metric-chart";
import { GraphPlate } from "@/components/landing/graph-plate";
import { usePageVisible } from "@/components/landing/use-field-state";
import { EvaluationTable } from "./evaluation-table";
import { SpotArt } from "./plate-heading";

export function ReplayScreen({ data }: { data: CurveData }) {
  const [step, setStep] = useState(200);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(4);
  const [metric, setMetric] = useState<LandingMetric>("file_acc@1");
  const visible = usePageVisible();
  const index = checkpointIndex(data, step);
  const point = data.curve[index];
  const seek = useCallback((value: number) => { setPlaying(false); setStep(clampStep(value, data.train)); }, [data.train]);
  const toggle = useCallback(() => {
    setPlaying((wasPlaying) => !wasPlaying);
    setStep((value) => value === data.train ? 0 : value);
  }, [data.train]);

  useEffect(() => {
    if (!playing || !visible) return;
    const timer = setTimeout(() => {
      if (step >= data.train - 1) { setStep(data.train); setPlaying(false); }
      else setStep(step + 1);
    }, 200 / speed);
    return () => clearTimeout(timer);
  }, [playing, visible, step, speed, data.train]);

  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (event.ctrlKey || event.metaKey || event.altKey || target?.closest("input, textarea, select, [contenteditable=true], dialog[open]") || document.querySelector("dialog[open]")) return;
      if (event.code === "Space" && !target?.closest("button, a, summary")) { event.preventDefault(); toggle(); }
      if (event.key === "[" || event.key === "]") { event.preventDefault(); seek(step + (event.key === "[" ? -1 : 1) * (event.shiftKey ? 10 : 1)); }
    };
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, [seek, step, toggle]);

  return (
    <div className="manual-page replay-layout">
      <section className="replay-sidebar" aria-labelledby="replay-screen-title">
        <div className="manual-kicker"><span className="sc">Plate ii</span><span className="sc">{playing ? "Playing" : "Paused"} at {speed}x</span></div>
        <h1 id="replay-screen-title" className="sr-only">Replay the learning pass</h1>
        <div className="replay-journal-number">{step}<span>/ {data.train}</span></div>
        <p className="manual-prose">Issues learned in the order Django fixed them. Each one: predict, see the real fix, learn.</p>
        <p className="replay-beat">The graph changes.<br /><i>The test set does not.</i></p>
        <div className="playback-controls">
          <button type="button" className="text-control" aria-label="Previous step" disabled={step === 0} onClick={() => seek(step - 1)}>‹ prev</button>
          <button type="button" className="btn replay-toggle" aria-label={playing ? "Pause replay" : "Play replay"} onClick={toggle}>{playing ? "Pause" : "Play"} <kbd>Space</kbd></button>
          <button type="button" className="text-control" aria-label="Next step" disabled={step === data.train} onClick={() => seek(step + 1)}>next ›</button>
        </div>
        <div className="replay-speeds" role="group" aria-label="Playback speed">{[1, 4, 8].map((value) => <button type="button" key={value} aria-pressed={speed === value} onClick={() => setSpeed(value)}>{value}x</button>)}</div>
        <button type="button" className="underlined-control" onClick={() => seek(data.train)}>Jump to the last step →</button>
        <figure className="replay-neighborhood"><figcaption className="cap"><b>FIG. 2</b> An illustrative neighborhood.</figcaption><div className="graph-stage"><GraphPlate step={step} /></div><p className="figure-note">Placeholder layout and deltas. Vermilion reweights are illustrative.</p></figure>
        <SpotArt chapter="replay" />
      </section>
      <section className="replay-main" aria-label="Held-out learning curve and step ruler">
        <div className="section-rule"><h2><span className="sc">Fig. 1</span> The held-out record</h2><span className="cap">{data.holdout} issues, never learned from</span></div>
        <div className="replay-chart-meta"><div className="manual-metric-switch" role="group" aria-label="Evaluation metric">{(Object.keys(metricLabels) as LandingMetric[]).map((value) => <button type="button" key={value} aria-pressed={metric === value} onClick={() => setMetric(value)}>{metricLabels[value]}</button>)}</div><p className="cap">Checkpoint {point.step}: <span className="num">{formatPercent(point[metric])}</span></p></div>
        <div className="manual-chart-scroll replay-chart" tabIndex={0} role="region" aria-label="Held-out accuracy chart, use the step slider to seek"><MetricChart data={data} metric={metric} index={index} step={step} onSeek={seek} wide /></div>
        <p className="figure-note replay-chart-note">Lines join measured checkpoints, including the dip. Between checkpoints, the score stays at the last measurement. Function Acc@10 ends at {formatPercent(data.curve.at(-1)!["function_acc@10"])}. Baselines are single-point references.</p>
        <div className="checkpoint-sheet"><p className="cap"><b>FIG. 3</b> Checkpoint register / {metricLabels[metric]}, not a mutation log.</p><div className="checkpoint-buttons">{data.curve.map((value) => <button type="button" key={value.step} aria-label={`Seek to step ${value.step}`} aria-pressed={point.step === value.step} onClick={() => seek(value.step)}><span className="num">{value.step}</span><span className="serif">{formatPercent(value[metric])}</span></button>)}</div></div>
        <div className="step-ruler"><label htmlFor="dashboard-replay-step"><span className="sc">Fixes learned, in time order</span><output className="num" htmlFor="dashboard-replay-step">{step} / {data.train}</output></label><input type="range" id="dashboard-replay-step" min={0} max={data.train} value={step} onChange={(event) => seek(Number(event.target.value))} aria-valuetext={`Step ${step} of ${data.train}. Last measured checkpoint ${point.step}, ${metricLabels[metric]} ${formatPercent(point[metric])}.`} /><div className="ruler-labels num"><span>0</span><span>80</span><span>160</span><span>240</span><span>320</span></div></div>
        <EvaluationTable data={data} metric={metric} note="Step 0 is the starting graph for this pass. The frozen reference used an older ranker. Playback starts paused, including with reduced motion." />
      </section>
    </div>
  );
}
