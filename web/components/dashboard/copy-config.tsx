"use client";

import { useRef, useState } from "react";

export function CopyConfig({ snippet }: { snippet: string }) {
  const source = useRef<HTMLPreElement>(null);
  const [status, setStatus] = useState("");
  return <div className="config-sheet"><div className="config-sheet-head"><span className="sc">MCP client configuration / local example</span><button type="button" onClick={async () => {
    try { await navigator.clipboard.writeText(snippet); setStatus("Copied"); }
    catch {
      if (source.current) {
        const range = document.createRange();
        range.selectNodeContents(source.current);
        const selection = window.getSelection();
        selection?.removeAllRanges(); selection?.addRange(range);
        source.current.focus();
      }
      setStatus("Select and copy the configuration");
    }
  }}>Copy JSON</button></div><pre ref={source} tabIndex={0} role="region" aria-label="Example MCP client configuration">{snippet}</pre><p className="copy-config-status cap" role="status">{status || "Replace the absolute path before use. This example has not been connection-tested."}</p></div>;
}
