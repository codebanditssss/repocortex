"use client";

import { useRef, useState } from "react";
import { copyText } from "@/lib/clipboard";

export function CopyConfig({
  snippet,
  title = "MCP client configuration / local example",
  buttonLabel = "Copy JSON",
  note = "Replace the absolute path before use. This example has not been connection-tested.",
}: { snippet: string; title?: string; buttonLabel?: string; note?: string }) {
  const source = useRef<HTMLPreElement>(null);
  const [status, setStatus] = useState("");
  return <div className="config-sheet"><div className="config-sheet-head"><span className="sc">{title}</span><button type="button" onClick={async () => {
    if (await copyText(snippet)) { setStatus("Copied"); }
    else {
      if (source.current) {
        source.current.focus({ preventScroll: true });
        const range = document.createRange();
        range.selectNodeContents(source.current);
        const selection = window.getSelection();
        selection?.removeAllRanges(); selection?.addRange(range);
      }
      setStatus("Automatic copy is blocked. Text selected: press Ctrl+C or ⌘C, or use your device’s Copy menu.");
    }
  }}>{status === "Copied" ? "Copied!" : buttonLabel}</button></div><pre ref={source} tabIndex={0} role="region" aria-label={title}>{snippet}</pre><p className="copy-config-status cap" role="status">{status || note}</p></div>;
}
