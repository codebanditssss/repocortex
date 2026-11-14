"use client";

import { memo, useEffect, useMemo, useRef, useState } from "react";
import { loadGraph, loadSnapshots, type GraphData, type SnapshotsData } from "@/lib/data";
import { plate } from "@/lib/graph";
import { snapshotAtStep } from "@/lib/landing";
import { useInView, usePageVisible } from "./use-field-state";

let cached: Promise<[GraphData, SnapshotsData]> | undefined;
function getPrintData() {
  cached ??= Promise.all([loadGraph(), loadSnapshots()]).catch((error) => {
    cached = undefined;
    throw error;
  });
  return cached;
}

const project = (value: number, extent: number) => (.05 + value * .9) * extent;

export const GraphPlate = memo(function GraphPlate({ step = 0, modules = false }: {
  step?: number; modules?: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const inView = useInView(container, "180px");
  const pageVisible = usePageVisible();
  const [data, setData] = useState<[GraphData, SnapshotsData] | null>(null);
  const [error, setError] = useState(false);
  const [size, setSize] = useState(0);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!inView || data || error) return;
    let cancelled = false;
    getPrintData().then((result) => { if (!cancelled) setData(result); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [inView, data, error, attempt]);

  useEffect(() => {
    if (!container.current) return;
    const observer = new ResizeObserver(() => setSize((value) => value + 1));
    observer.observe(container.current);
    return () => observer.disconnect();
  }, []);

  const print = useMemo(() => {
    if (!data) return null;
    const [graph, snapshots] = data;
    const checkpoint = snapshotAtStep(snapshots, step);
    const weights = new Map(checkpoint.edge_deltas.map((edge) => [`${edge.s}:${edge.t}`, edge.w]));
    // Exclude fictional shortcuts rather than presenting them as measured mutations.
    const edges = graph.edges.filter((edge) => edge.type !== "SHORTCUT");
    const strengthened = edges.filter((edge) => (weights.get(`${edge.s}:${edge.t}`) ?? edge.w) > edge.w);
    const groups = new Map<string, { x: number; y: number; count: number }>();
    graph.nodes.forEach((node) => {
      const group = groups.get(node.file) ?? { x: 0, y: 0, count: 0 };
      group.x += node.x; group.y += node.y; group.count++;
      groups.set(node.file, group);
    });
    return {
      graph,
      field: {
        nodes: graph.nodes.map((node) => ({ id: node.id, x: node.x, y: node.y })),
        edges: edges.map((edge) => ({ ...edge, w: weights.get(`${edge.s}:${edge.t}`) ?? edge.w })),
      },
      strengthened,
      labels: [...groups].map(([file, point]) => ({ file, x: point.x / point.count, y: point.y / point.count })),
    };
  }, [data, step]);

  useEffect(() => {
    if (!canvas.current || !print || !inView || !pageVisible) return;
    const frame = requestAnimationFrame(() => {
      if (!canvas.current) return;
      const printScale = Math.min(1, canvas.current.clientWidth / 1000);
      const projectNode = plate(canvas.current, print.field, {
        mode: "atkinson", cell: 1, pad: .05, nodeR: 4.5 * printScale,
        edgeAlpha: .15, edgeW: 1.1, glow: .18, noise: .018,
      });
      // As in the locked v3 plates, fine structural rules sit over the stipple.
      // They preserve readable connections that a 1-bit threshold can lose.
      const context = canvas.current.getContext("2d");
      if (!context) return;
      const dpr = window.devicePixelRatio || 1;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      context.strokeStyle = "rgba(28,25,20,.27)";
      context.lineWidth = .55;
      context.beginPath();
      for (const edge of print.field.edges) {
        const a = projectNode(print.field.nodes[edge.s]);
        const b = projectNode(print.field.nodes[edge.t]);
        context.moveTo(a.x, a.y);
        context.lineTo(b.x, b.y);
      }
      context.stroke();
      context.fillStyle = "#1C1914";
      context.beginPath();
      const radius = Math.max(.45, .8 * printScale);
      for (const node of print.field.nodes) {
        const point = projectNode(node);
        context.moveTo(point.x + radius, point.y);
        context.arc(point.x, point.y, radius, 0, Math.PI * 2);
      }
      context.fill();
    });
    return () => cancelAnimationFrame(frame);
  }, [print, inView, pageVisible, size]);

  return (
    <div className="graph-print" ref={container} data-step={step} data-ready={Boolean(print)}>
      <canvas ref={canvas} aria-hidden="true" />
      {print && (
        <>
          <svg aria-hidden="true" viewBox="0 0 1000 600" preserveAspectRatio="none">
            {print.strengthened.map((edge) => {
              const a = print.graph.nodes[edge.s];
              const b = print.graph.nodes[edge.t];
              return <line key={`${edge.s}:${edge.t}`} x1={project(a.x, 1000)} y1={project(a.y, 600)} x2={project(b.x, 1000)} y2={project(b.y, 600)} stroke="var(--red)" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />;
            })}
          </svg>
          {modules && print.labels.map((label) => <span className="graph-module news" key={label.file} style={{ left: `${project(label.x, 100)}%`, top: `${project(label.y, 100) - 13}%` }}>{label.file.replace("django/", "").replace("/__init__.py", "").replace(".py", "").replaceAll("/", ".")}</span>)}
        </>
      )}
      {error && <div className="graph-error"><p>The graph plate could not be loaded. The evaluation is still available below.</p><button type="button" onClick={() => { setError(false); setAttempt((value) => value + 1); }}>Retry graph</button></div>}
    </div>
  );
});
