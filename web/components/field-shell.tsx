"use client";

import Link from "next/link";
import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { chapters, chapterForPath } from "@/lib/chapters";
import evaluation from "@/public/data/curve.json";
import { KeyboardShortcuts } from "@/components/dashboard/keyboard-shortcuts";

export function FieldShell({
  children,
  dashboard = false,
}: {
  children: React.ReactNode;
  dashboard?: boolean;
}) {
  const pathname = usePathname();
  const active = chapterForPath(pathname);

  useEffect(() => {
    if (!window.location.hash) {
      window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    }
  }, [pathname]);

  return (
    <div className={`field-shell${dashboard ? " dashboard-shell" : ""}`}>
      <header className={`head${dashboard ? "" : " home-head"}`}>
        <Link href="/" className="mark" aria-label="RepoCortex home">
          Repo<i>Cortex</i>
        </Link>
        {dashboard ? (
          <nav className="chap" aria-label="Field manual chapters">
            {chapters.map((chapter) => (
              <Link
                key={chapter.slug}
                href={chapter.href}
                aria-current={active.slug === chapter.slug ? "page" : undefined}
              >
                <span className="roman" aria-hidden="true">{chapter.roman}</span>
                {chapter.label}
              </Link>
            ))}
          </nav>
        ) : (
          <>
            <span className="head-note sc">Code, connected by experience</span>
            <Link className="home-nav" href="/app">Field manual</Link>
          </>
        )}
        <div className="meta">
          <div>
            <b>django/django</b>, <span className="num">{evaluation.train}</span> train
            {" / "}<span className="num">{evaluation.holdout}</span> held out
          </div>
          <div title="Static demo status. A live backend connection has not been checked.">
            HydraDB / recorded snapshot
          </div>
        </div>
      </header>
      <main id="main-content" className="stage" tabIndex={-1}>
        {children}
      </main>
      <footer className="foot">
        <i>
          Measured held-out numbers: {evaluation.train} training fixes, {evaluation.holdout} held-out fix rows.
          {dashboard && ["locate", "agent", "load", "graph", "replay"].includes(active.slug)
            ? " Illustrative fixtures are marked as placeholders."
            : ""}
        </i>
        <span className="footer-actions">
          <a href="https://github.com/codebanditssss/hydradb-hack" target="_blank" rel="noreferrer" aria-label="RepoCortex source on GitHub (opens in a new tab)">GitHub ↗</a>
          <span>RepoCortex field manual{dashboard ? `, plate ${active.roman} of vii` : ""}</span>
          {dashboard && <KeyboardShortcuts />}
        </span>
      </footer>
    </div>
  );
}
