"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Core, ElementDefinition } from "cytoscape";
import type { Trace, TraceNode } from "@/lib/types";
import { KIND_LABEL, pct, shortAddr, tone, usdt } from "@/lib/format";
import NodeDetail from "./NodeDetail";
import styles from "./TraceGraph.module.css";

const COL_W = 340;
const ROW_H = 104;
const STEP_MS = 900;

const TONE_COLOR = {
  trace: "#2c5a86",
  exchange: "#b8322a",
  hold: "#c28e14",
  frozen: "#2f7f95",
  dead: "#8b959f",
} as const;
const TONE_FILL = {
  trace: "#f7f9fb",
  exchange: "#f7f9fb",
  hold: "#f6e7bf",
  frozen: "#dcedf1",
  dead: "#eef1f4",
} as const;

function nodeText(n: TraceNode) {
  const full = n.label ?? shortAddr(n.address);
  const name = full.length > 22 ? `${full.slice(0, 21)}…` : full;
  const sub = n.frozen?.is_frozen ? "TETHER FROZE THIS" : KIND_LABEL[n.kind].toUpperCase();
  return `${name}\n${sub}`;
}

/** Deterministic column layout: x = depth, rows sorted by inflow (largest on top). */
function buildElements(trace: Trace): ElementDefinition[] {
  const inflow = new Map<string, number>();
  for (const e of trace.edges) inflow.set(e.to, (inflow.get(e.to) ?? 0) + e.attributed_amount);

  const byDepth = new Map<number, TraceNode[]>();
  for (const n of trace.nodes) byDepth.set(n.depth, [...(byDepth.get(n.depth) ?? []), n]);

  const els: ElementDefinition[] = [];
  const maxRows = Math.max(...[...byDepth.values()].map((c) => c.length));
  for (const [depth, col] of byDepth) {
    col.sort((a, b) => (inflow.get(b.address) ?? 0) - (inflow.get(a.address) ?? 0) || a.address.localeCompare(b.address));
    const top = ((maxRows - col.length) * ROW_H) / 2;
    els.push({
      group: "nodes",
      data: { id: `hdr-${depth}`, text: depth === 0 ? "VICTIM" : `HOP ${depth}`, depth },
      position: { x: depth * COL_W, y: -ROW_H * 0.85 },
      classes: "hdr",
      selectable: false,
      grabbable: false,
    });
    col.forEach((n, i) => {
      const t = tone(n);
      els.push({
        group: "nodes",
        data: { id: n.address, text: nodeText(n), depth, color: TONE_COLOR[t], fill: TONE_FILL[t] },
        position: { x: depth * COL_W, y: top + i * ROW_H },
        classes: t === "dead" ? "dead" : "",
      });
    });
  }
  for (const e of trace.edges) {
    els.push({
      group: "edges",
      data: {
        id: `${e.from}->${e.to}`,
        source: e.from,
        target: e.to,
        hop: e.hop,
        text: `${usdt(e.attributed_amount)}\n${pct(e.confidence)} · ${e.method}`,
        width: 1.5 + Math.log10(Math.max(e.attributed_amount, 10)) * 0.9,
      },
      classes: e.confidence < 0.6 ? "weak" : "",
    });
  }
  return els;
}

export default function TraceGraph({ trace }: { trace: Trace }) {
  const box = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [shownHop, setShownHop] = useState(0);
  const maxHop = useMemo(() => Math.max(0, ...trace.edges.map((e) => e.hop)), [trace]);

  const reveal = useCallback((hop: number) => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.elements().forEach((el) => {
        el.toggleClass("pending", el.data(el.isEdge() ? "hop" : "depth") > hop);
      });
    });
    setShownHop(hop);
  }, []);

  const play = useCallback(() => {
    if (timer.current) clearInterval(timer.current);
    reveal(0);
    let hop = 0;
    timer.current = setInterval(() => {
      hop += 1;
      reveal(hop);
      if (hop >= maxHop && timer.current) clearInterval(timer.current);
    }, STEP_MS);
  }, [maxHop, reveal]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const cytoscape = (await import("cytoscape")).default;
      if (cancelled || !box.current) return;
      const css = getComputedStyle(document.documentElement);
      const mono = css.getPropertyValue("--font-mono").trim() || "monospace";
      const display = css.getPropertyValue("--font-display").trim() || "sans-serif";

      const cy = cytoscape({
        container: box.current,
        elements: buildElements(trace),
        layout: { name: "preset", padding: 40 },
        minZoom: 0.3,
        maxZoom: 2,
        wheelSensitivity: 0.2,
        style: [
          {
            selector: "node",
            style: {
              shape: "round-rectangle",
              width: 196,
              height: 58,
              "background-color": "data(fill)",
              "border-color": "data(color)",
              "border-width": 2.5,
              label: "data(text)",
              "text-wrap": "wrap",
              "text-valign": "center",
              "font-family": mono,
              "font-size": 14,
              color: "#15212e",
              "line-height": 1.35,
              "transition-property": "opacity",
              "transition-duration": 450,
            },
          },
          { selector: "node.dead", style: { "border-style": "dashed" } },
          { selector: "node:selected", style: { "border-width": 4, "overlay-opacity": 0 } },
          {
            selector: "node.hdr",
            style: {
              shape: "rectangle",
              width: 1,
              height: 1,
              "background-opacity": 0,
              "border-width": 0,
              label: "data(text)",
              "font-family": display,
              "font-weight": 700,
              "font-size": 15,
              color: "#4b5967",
              "text-margin-y": 0,
            },
          },
          {
            selector: "edge",
            style: {
              "curve-style": "bezier",
              width: "data(width)",
              "line-color": "#4b5967",
              "target-arrow-color": "#4b5967",
              "target-arrow-shape": "triangle",
              "arrow-scale": 0.9,
              label: "data(text)",
              "text-wrap": "wrap",
              "font-family": mono,
              "font-size": 13,
              color: "#15212e",
              "text-background-color": "#e8edf1",
              "text-background-opacity": 1,
              "text-background-padding": "2px",
              "transition-property": "opacity",
              "transition-duration": 450,
            },
          },
          { selector: "edge.weak", style: { "line-style": "dashed", opacity: 0.75 } },
          { selector: ".pending", style: { opacity: 0, events: "no" } },
        ],
      });
      cy.on("tap", "node", (ev) => {
        if (!ev.target.hasClass("hdr")) setSelected(ev.target.id());
      });
      cy.on("tap", (ev) => {
        if (ev.target === cy) setSelected(null);
      });
      cyRef.current = cy;

      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (reduced) reveal(maxHop);
      else play();
    })().catch((err) => {
      console.error("[hound-web] trace graph failed to render:", err);
      if (box.current) box.current.textContent = `Trace graph failed to render: ${err}`;
    });
    return () => {
      cancelled = true;
      if (timer.current) clearInterval(timer.current);
      cyRef.current?.destroy();
      cyRef.current = null;
    };
  }, [trace, maxHop, play, reveal]);

  const node = selected ? trace.nodes.find((n) => n.address === selected) ?? null : null;

  return (
    <section className={styles.wrap} aria-label="Money trail">
      <div className={styles.controls}>
        <span className={styles.progress}>
          {shownHop >= maxHop ? `${maxHop} hops traced` : `Tracing hop ${shownHop} of ${maxHop}…`}
        </span>
        <button type="button" onClick={play}>Replay trace</button>
        <button type="button" onClick={() => reveal(maxHop)} disabled={shownHop >= maxHop}>
          Show all hops
        </button>
        <button type="button" onClick={() => cyRef.current?.fit(undefined, 40)}>Fit to screen</button>
      </div>
      <ul className={styles.legend} aria-label="Legend">
        <li data-tone="trace">Victim / intermediate</li>
        <li data-tone="exchange">Exchange</li>
        <li data-tone="hold">Holding, freezable</li>
        <li data-tone="frozen">Tether froze this</li>
        <li data-tone="dead">Dead end</li>
        <li data-tone="weak">Under 60% confidence</li>
      </ul>
      <div ref={box} className={styles.canvas} />
      {node && <NodeDetail trace={trace} node={node} onClose={() => setSelected(null)} />}
    </section>
  );
}
