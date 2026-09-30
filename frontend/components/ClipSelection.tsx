"use client";

import { Scissors } from "lucide-react";
import { type RefObject, useEffect, useState } from "react";

const TEX = 'annotation[encoding="application/x-tex"]';

/** KaTeX back to its TeX source, so a clipped formula renders again in the scratchpad. */
function untex(box: HTMLElement) {
  box.querySelectorAll(".katex-display").forEach((d) => {
    const tex = d.querySelector(TEX)?.textContent;
    d.replaceWith(tex ? `\n$$${tex}$$\n` : (d.querySelector(".katex-html")?.textContent ?? ""));
  });
  box.querySelectorAll(".katex").forEach((k) => {
    const tex = k.querySelector(TEX)?.textContent;
    k.replaceWith(tex ? `$${tex}$` : (k.querySelector(".katex-html")?.textContent ?? ""));
  });
}

/** The selected answer text as Markdown, and the citation numbers of the claims it touches. */
export function readSelection(root: HTMLElement, range: Range): { text: string; cites: number[] } {
  const cites = new Set<number>();
  root.querySelectorAll(".claim").forEach((c) => {
    if (range.intersectsNode(c)) c.querySelectorAll(".margin-tabs .tab").forEach((t) => cites.add(Number(t.textContent)));
  });
  const box = document.createElement("div");
  box.append(range.cloneContents());
  box.querySelectorAll("button.cite").forEach((b) => cites.add(Number(b.textContent)));
  box.querySelectorAll("button.cite, sup.cite, .margin-tabs").forEach((e) => e.remove());
  untex(box);
  box.querySelectorAll("li").forEach((li) => li.prepend("- "));
  box.querySelectorAll("p, li, h3, h4, tr").forEach((e) => e.append("\n"));
  const text = (box.textContent ?? "")
    .replace(/[ \t]+([.,;:])/g, "$1") // where a citation marker sat before the punctuation
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return { text, cites: [...cites].filter(Number.isFinite).sort((a, b) => a - b) };
}

/** A Clip button that floats under a selection inside `root`. */
export function ClipSelection({
  root,
  onClip,
}: {
  root: RefObject<HTMLElement | null>;
  onClip: (text: string, cites: number[]) => void;
}) {
  const [at, setAt] = useState<{ x: number; y: number } | null>(null);

  useEffect(() => {
    const place = () => {
      const sel = document.getSelection();
      const el = root.current;
      if (!sel || sel.isCollapsed || !sel.rangeCount || !el) return setAt(null);
      const r = sel.getRangeAt(0);
      if (!el.contains(r.commonAncestorContainer) || !sel.toString().trim()) return setAt(null);
      const rect = r.getBoundingClientRect();
      setAt({ x: rect.right, y: rect.bottom });
    };
    document.addEventListener("selectionchange", place);
    window.addEventListener("scroll", place, true);
    return () => {
      document.removeEventListener("selectionchange", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [root]);

  if (!at) return null;
  return (
    <button
      type="button"
      className="clip-float"
      style={{ left: at.x, top: at.y }}
      // keep the selection: a mousedown here would otherwise clear it before the click
      onMouseDown={(e) => e.preventDefault()}
      onClick={() => {
        const sel = document.getSelection();
        const el = root.current;
        if (!sel?.rangeCount || !el) return;
        const { text, cites } = readSelection(el, sel.getRangeAt(0));
        if (text) onClip(text, cites);
        sel.removeAllRanges();
        setAt(null);
      }}
    >
      <Scissors size={14} aria-hidden />
      Clip
    </button>
  );
}
