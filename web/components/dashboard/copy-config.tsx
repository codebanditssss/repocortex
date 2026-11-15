"use client";

import { useRef, useState } from "react";

export function CopyConfig({
  snippet,
  title = "MCP client configuration / local example",
  buttonLabel = "Copy JSON",
  note = "Replace the absolute path before use. This example has not been connection-tested.",
}: { snippet: string; title?: string; buttonLabel?: string; note?: string }) {
  const source = useRef<HTMLPreElement>(null);
  const [status, setStatus] = useState("");
  return <div className="config-sheet"><div className="config-sheet-head"><span className="sc">{title}</span><button type="button" onClick={async () => {
    try { await navigator.clipboard.writeText(snippet); setStatus("Copied"); }
    catch {
      if (source.current) {
        const range = document.createRange();
        range.selectNodeContents(source.current);
        const selection = window.getSelection();
        selection?.removeAllRanges(); selection?.addRange(range);
        source.current.focus();
      }
      setStatus("Text selected. Copy it using your keyboard.");
    }
  }}>{buttonLabel}</button></div><pre ref={source} tabIndex={0} role="region" aria-label={title}>{snippet}</pre><p className="copy-config-status cap" role="status">{status || note}</p></div>;
}
