"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
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
  const more = useRef<HTMLDetailsElement>(null);
  const primary = chapters.filter((chapter) => ["overview", "locate", "connect"].includes(chapter.slug));
  const secondary = chapters.filter((chapter) => !primary.includes(chapter));

  useEffect(() => {
    if (more.current) more.current.open = false;
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
          <nav className="chap" aria-label="Main navigation">
            {primary.map((chapter) => (
              <Link key={chapter.slug} href={chapter.href}
                aria-current={active.slug === chapter.slug ? "page" : undefined}>
                {chapter.label}
              </Link>
            ))}
            <details className="nav-more" ref={more} onKeyDown={(event) => {
              if (event.key === "Escape" && more.current) {
                more.current.open = false;
                more.current.querySelector("summary")?.focus();
              }
            }} onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false;
            }}>
              <summary>{secondary.some((chapter) => chapter.slug === active.slug) ? active.label : "More"}<span aria-hidden="true">⌄</span></summary>
              <div className="nav-more-links">
                {secondary.map((chapter) => <Link key={chapter.slug} href={chapter.href}
                  aria-current={active.slug === chapter.slug ? "page" : undefined}>{chapter.label}</Link>)}
              </div>
            </details>
          </nav>
        ) : (
          <>
            <span className="head-note sc">Code, connected by experience</span>
            <Link className="home-nav" href="/app">Field manual</Link>
          </>
        )}

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
          <a href="https://github.com/codebanditssss/repocortex" target="_blank" rel="noreferrer" aria-label="RepoCortex source on GitHub (opens in a new tab)">GitHub ↗</a>
          {dashboard && <KeyboardShortcuts />}
          <span className="footer-edition">RepoCortex field manual{dashboard ? `, plate ${active.roman} of vii` : ""}</span>
        </span>
      </footer>
    </div>
  );
}
