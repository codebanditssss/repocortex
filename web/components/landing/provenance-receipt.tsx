"use client";

import { useRef } from "react";
import type { ProvenanceHit, ProvenanceIssue } from "@/lib/data";
import { provenanceLines } from "@/lib/landing";
import { useInView, useReducedMotion } from "./use-field-state";
import "./provenance-receipt.css";

export function ProvenanceReceipt({ ticket, hit }: { ticket: ProvenanceIssue; hit?: ProvenanceHit }) {
  const ref = useRef<HTMLPreElement>(null);
  const visible = useInView(ref, "0px", true);
  const reduced = useReducedMotion();
  return (
    <pre ref={ref} className={`provenance-tree ${visible && !reduced ? "receipt-reveal" : ""}`} tabIndex={0} aria-label={`Measured provenance route for issue #${ticket.ticket}`}>
      {provenanceLines(ticket, hit).map((line, index) => (
        <span className={line.includes("gold match") ? "actual-line" : ""} key={index} style={{ animationDelay: `${index * 70}ms` }}>{line || " "}</span>
      ))}
    </pre>
  );
}
