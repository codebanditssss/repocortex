"use client";

import { useCallback, useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { chapters } from "@/lib/chapters";

const keys = ["O", "R", "L", "A", "D", "G", "C"];

export function KeyboardShortcuts() {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const pathname = usePathname();
  const router = useRouter();
  const toggle = useCallback(() => {
    if (dialog.current?.open) dialog.current.close();
    else dialog.current?.showModal();
  }, []);

  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      if (dialog.current?.open && event.key === "Tab") {
        const controls = Array.from(dialog.current.querySelectorAll<HTMLElement>("button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex='0']"));
        if (controls.length) {
          event.preventDefault();
          const current = controls.indexOf(document.activeElement as HTMLElement);
          const next = current < 0 ? (event.shiftKey ? controls.length - 1 : 0) : (current + (event.shiftKey ? -1 : 1) + controls.length) % controls.length;
          controls[next].focus();
        }
        return;
      }
      if (event.ctrlKey || event.metaKey || event.altKey || (event.target as HTMLElement)?.closest("input, textarea, select, [contenteditable=true]")) return;
      if (event.key === "?") { event.preventDefault(); toggle(); return; }
      if (dialog.current?.open) return;
      const index = keys.indexOf(event.key.toUpperCase());
      if (index !== -1) { event.preventDefault(); router.push(chapters[index].href); }
      else if (event.key.toLowerCase() === "k" && pathname !== "/app/locate") {
        event.preventDefault(); router.push("/app/locate?focus=1");
      }
    };
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, [pathname, router, toggle]);

  return <>
    <button ref={trigger} type="button" className="shortcuts-trigger" aria-label="Keyboard shortcuts" aria-haspopup="dialog" onClick={toggle}>Shortcuts</button>
    <dialog ref={dialog} className="shortcuts-dialog" aria-labelledby="shortcuts-title" aria-describedby="shortcuts-description" onClose={() => trigger.current?.focus()} onClick={(event) => {
      if (event.target === event.currentTarget) {
        const bounds = event.currentTarget.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) event.currentTarget.close();
      }
    }}>
      <div className="section-rule"><h2 id="shortcuts-title">Keyboard <i>shortcuts</i></h2><button type="button" className="text-control" onClick={() => dialog.current?.close()}>Close <kbd>Esc</kbd></button></div>
      <p id="shortcuts-description" className="figure-note">Press ? to toggle. Shortcuts stay out of text fields.</p>
      <dl>{chapters.map((chapter, index) => <div key={chapter.slug}><dt>{chapter.label}</dt><dd><kbd>{keys[index]}</kbd></dd></div>)}<div><dt>Focus Locate composer</dt><dd><kbd>K</kbd></dd></div><div><dt>Play / pause on Replay</dt><dd><kbd>Space</kbd></dd></div><div><dt>Previous / next replay step</dt><dd><kbd>[</kbd> <kbd>]</kbd></dd></div><div><dt>Close shortcuts</dt><dd><kbd>Esc</kbd></dd></div></dl>
    </dialog>
  </>;
}
