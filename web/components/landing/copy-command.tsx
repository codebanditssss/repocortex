"use client";

import { useRef, useState, useEffect } from "react";
import { copyText } from "@/lib/clipboard";

const command = ".venv/bin/python scripts/mcp_server.py --http --port 8766";

export function CopyCommand() {
  const [status, setStatus] = useState("");
  const commandRef = useRef<HTMLElement>(null);
  const timeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (timeout.current) clearTimeout(timeout.current); }, []);

  async function copy() {
    if (timeout.current) clearTimeout(timeout.current);
    if (await copyText(command)) {
      setStatus("Copied");
      timeout.current = setTimeout(() => setStatus(""), 3500);
    } else {
      const range = document.createRange();
      if (commandRef.current) range.selectNodeContents(commandRef.current);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
      setStatus("Automatic copy is blocked. Text selected: press Ctrl+C or ⌘C, or use your device’s Copy menu.");
    }
  }

  return (
    <>
      <div className="command-line"><code ref={commandRef} className="num">{command}</code><button type="button" onClick={copy} aria-label="Copy local MCP startup command">{status === "Copied" ? "Copied" : "Copy"} <span aria-hidden="true">⧉</span></button></div>
      <span className="copy-status" role="status">{status}</span>
    </>
  );
}
