"use client";

import { useEffect, useRef } from "react";
import { grain } from "@/lib/graph";

export function PaperGrain() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (ref.current) {
      ref.current.style.backgroundImage = `url("${grain(256, 0.028, 4)}")`;
      ref.current.style.backgroundSize = "256px 256px";
    }
  }, []);

  return <div ref={ref} className="grain" aria-hidden="true" />;
}
