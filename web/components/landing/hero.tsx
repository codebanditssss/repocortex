"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import type { CurveData, ProvenanceIssue } from "@/lib/data";
import { fixedInRoutes, hitSymbol } from "@/lib/landing";
import { GraphPlate } from "./graph-plate";
import { useInView, usePageVisible, useReducedMotion } from "./use-field-state";

function typedLine(text: string, progress: number) {
  if (progress >= 1) return text;
  const count = Math.min(text.length, Math.ceil(Math.max(0, progress) * text.length));
  return text.slice(0, count);
}

export function Hero({ ticket, evaluation, plate }: {
  ticket: ProvenanceIssue;
  evaluation: CurveData;
  plate: ReactNode;
}) {
  const ref = useRef<HTMLElement>(null);
  const visible = useInView(ref);
  const pageVisible = usePageVisible();
  const reduced = useReducedMotion();
  const [progress, setProgress] = useState(1);
  const [playing, setPlaying] = useState(false);
  const [optedIn, setOptedIn] = useState(false);
  const [started, setStarted] = useState(false);
  const [run, setRun] = useState(0);
  const elapsed = useRef(10000);
  const autoStarted = useRef(false);

  const play = useCallback((manual = true) => {
    setOptedIn(manual);
    setStarted(true);
    elapsed.current = 0;
    setProgress(0);
    setPlaying(true);
    setRun((value) => value + 1);
  }, []);

  useEffect(() => {
    if (reduced || !visible || !pageVisible || autoStarted.current) return;
    const timeout = setTimeout(() => {
      if (!autoStarted.current) { autoStarted.current = true; play(false); }
    }, 900);
    return () => clearTimeout(timeout);
  }, [visible, pageVisible, reduced, play]);

  useEffect(() => {
    if (!playing || !visible || !pageVisible || (reduced && !optedIn)) return;
    let frame = 0;
    let previous = 0;
    let lastPaint = 0;
    const tick = (now: number) => {
      if (previous) elapsed.current = Math.min(10000, elapsed.current + now - previous);
      previous = now;
      if (now - lastPaint > 75 || elapsed.current >= 10000) {
        setProgress(elapsed.current / 10000);
        lastPaint = now;
      }
      if (elapsed.current < 10000) frame = requestAnimationFrame(tick);
      else setPlaying(false);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, visible, pageVisible, reduced, optedIn, run]);

  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (event.code !== "Space" || !visible || event.repeat || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.target instanceof Element && event.target.closest("a,button,input,textarea,select,[contenteditable]")) return;
      event.preventDefault();
      autoStarted.current = true;
      play();
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [visible, play]);

  const shown = reduced && !optedIn ? 1 : started ? progress : 0;
  const typing = Math.min(1, shown / .32);
  const routeReady = shown > .32;
  const found = shown > .62;
  const last = evaluation.curve[evaluation.curve.length - 1];
  const hit = ticket.hits.find((hit) => hit.gold)!;
  const route = fixedInRoutes(hit.path)[0];
  const symbol = hitSymbol(hit).replace("django.db.models.query.", "");
  const ticketText = `Issue #${ticket.ticket}: ${symbol}`;
  const typedTicket = typedLine(ticketText, typing);

  return (
    <section className="hero" ref={ref} aria-labelledby="page-title">
      <div className="hero-running">
        <p className="sc"><span className="num">00</span> / A graph with a memory</p>
        <p className="hero-counter"><span className="sc">PRs learned</span><span className="num">{String(last.step).padStart(4, "0")}</span><span className="news">django/django</span></p>
      </div>
      <div className="hero-plate">
        {plate}
        <div className="hero-live-graph">
          <GraphPlate />
          <div className={`hero-route ${routeReady ? "is-seeded" : ""} ${found ? "is-found" : ""}`} aria-label={`Measured route for held-out issue #${ticket.ticket}`}>
          <p className="sc route-inset-label">Held-out issue → past fix → gold function</p>
          <svg viewBox="0 0 600 240" preserveAspectRatio="none" aria-hidden="true">
            <path className="route-ink" d="M40 152 L240 70 L510 130" />
            {routeReady && <path className={playing && visible && pageVisible ? "route-pulse" : "route-learned"} d="M40 152 L240 70 L510 130" />}
            <path className="route-leader" d="M240 70 L240 35 M510 130 L510 169" />
            <circle cx="40" cy="152" r="4" /><circle cx="240" cy="70" r="4" /><circle cx="510" cy="130" r="4" />
          </svg>
          <div className="route-seed"><span className="sc">Held out</span><span>Issue #{ticket.ticket}</span></div>
          <div className="route-prediction route-prediction-one"><span>Issue #{route.ticket}</span><small className="num">similarity {route.similarity}</small></div>
          <div className="route-prediction route-prediction-two"><span>{symbol}</span><small className="num">FIXED_IN / weight {route.weight}</small></div>
          <div className={`fix-annotation ${found ? "is-visible" : ""}`}><span className="sc">Rank {hit.rank} / gold match</span><span className="num">score {hit.score}</span></div>
          <p className="route-fixture-note news">Measured path, drawn schematically.</p>
          </div>
        </div>
      </div>
      <div className="hero-copy">
        <p className="hero-eyebrow news">Not another search. A little more understanding.</p>
        <h1 id="page-title">Every merged fix makes it better at finding <i>the next bug.</i></h1>
        <p className="hero-dek">RepoCortex keeps a graph of your codebase in HydraDB. Hand it a bug report and it walks that graph to the functions that need changing. When the real fix lands, it checks its own answer and rewires itself.</p>
        <div className="hero-actions"><a className="landing-primary" href="#replay">Watch it learn Django <span aria-hidden="true">↓</span></a><a className="text-link" href="#install">Add it to your agent <span aria-hidden="true">→</span></a></div>
      </div>
      <aside className="hero-ticket" aria-label="Measured held-out ticket">
        <div className="ticket-heading"><span className="sc">Held-out ticket / #{ticket.ticket}</span><span className="sc measured-label">Measured</span></div>
        <p className="ticket-title">
          <span className="sr-only">{ticketText}</span>
          <span className="ticket-title-sizer" aria-hidden="true">{ticketText}</span>
          <span className="ticket-title-typed" aria-hidden="true">{typedTicket}{playing && typing < 1 ? <span className="typing-caret" /> : null}</span>
        </p>
        <p className="ticket-file num">{hit.file}</p>
        <div className="ticket-controls"><span className="news">{found ? `Rank ${hit.rank}. Gold hit. Score ${hit.score}.` : routeReady ? "Following a past fix…" : "Reading the record…"}</span><button type="button" onClick={() => { autoStarted.current = true; play(); }}>{playing ? "Restart" : "Play"} <span aria-hidden="true">↻</span></button></div>
        <p className="sc ticket-space">Space replays this plate</p>
      </aside>
      <div className="hero-bottom"><p className="news">Held-out routes &amp; evaluation are measured. The graph layout is a placeholder; the mycelium is an illustration.</p><a className="sc" href="#replay">Replay {last.step} merged fixes <span aria-hidden="true">↓</span></a></div>
    </section>
  );
}
