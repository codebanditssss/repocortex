"use client";

import { useRef, useState, useEffect } from "react";

const command = "npx repocortex";

export function CopyCommand() {
  const [status, setStatus] = useState("");
  const commandRef = useRef<HTMLElement>(null);
  const timeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (timeout.current) clearTimeout(timeout.current); }, []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setStatus("Copied");
    } catch {
      const range = document.createRange();
      if (commandRef.current) range.selectNodeContents(commandRef.current);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
      setStatus("Select and copy the command");
    }
    if (timeout.current) clearTimeout(timeout.current);
    timeout.current = setTimeout(() => setStatus(""), 3500);
  }

  return (
    <>
      <div className="command-line"><code ref={commandRef} className="num">{command}</code><button type="button" onClick={copy} aria-label="Copy placeholder install command">{status === "Copied" ? "Copied" : "Copy"} <span aria-hidden="true">⧉</span></button></div>
      <span className="copy-status" role="status">{status}</span>
    </>
  );
}
