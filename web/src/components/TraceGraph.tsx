"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Core, ElementDefinition } from "cytoscape";
import type { Trace, TraceNode } from "@/lib/types";
import { KIND_LABEL, daysBetween, pct, shortAddr, tok0, tone } from "@/lib/format";
import { readFreezesShown, writeFreezesShown } from "@/lib/useTrace";
import NodeDetail from "./NodeDetail";
import styles from "./TraceGraph.module.css";

const COL_W = 360;
const ROW_H = 118;
const STEP_MS = 900;

const TONE_COLOR = {
  trace: "#2c5a86",
  exchange: "#b8322a",
  hold: "#c28e14",
  frozen: "#1f7a8c",
  dead: "#8b959f",
} as const;
// Meaning is carried by the fill, not the outline: solid teal = Tether froze it, solid red = exchange,
// solid blue = the victim, white = an intermediate wallet (readable from across a room).
const TONE_FILL = {
  trace: "#ffffff",
  exchange: "#b8322a",
  hold: "#f6e7bf",
  frozen: "#1f7a8c",
  dead: "#eef1f4",
} as const;
const TONE_INK = {
  trace: "#15212e",
  exchange: "#ffffff",
  hold: "#15212e",
  frozen: "#ffffff",
  dead: "#4b5967",
} as const;
const VICTIM_FILL = "#2c5a86";

/** Label and colours for a node; frozen styling waits until freezes are revealed. */
function nodeLook(n: TraceNode, freezesShown: boolean, swapped: boolean) {
  const full = n.label ?? shortAddr(n.address);
  const name = full.length > 22 ? `${full.slice(0, 21)}…` : full;
  const frozen = freezesShown && n.frozen?.is_frozen;
  const t = tone(n, freezesShown);
  const victim = n.depth === 0 && t === "trace";
  const sub = frozen ? "Tether froze this" : victim ? "Victim" : swapped ? "Swap ETH → USDT" : KIND_LABEL[n.kind];
  return {
    text: `${name}\n${sub}`,
    color: victim ? VICTIM_FILL : TONE_COLOR[t],
    fill: victim ? VICTIM_FILL : TONE_FILL[t],
    ink: victim ? "#ffffff" : TONE_INK[t],
    dead: t === "dead",
  };
}

/** Deterministic column layout: x = depth, rows sorted by inflow (largest on top). */
function buildElements(trace: Trace, freezesShown: boolean): ElementDefinition[] {
  const swapped = swapAddresses(trace);
  const toUsdt = usdtPerUnit(trace);
  const inflow = new Map<string, number>();
  for (const e of trace.edges) inflow.set(e.to, (inflow.get(e.to) ?? 0) + e.attributed_amount * toUsdt(e.token));

  const byDepth = new Map<number, TraceNode[]>();
  for (const n of trace.nodes) byDepth.set(n.depth, [...(byDepth.get(n.depth) ?? []), n]);

  const els: ElementDefinition[] = [];
  const maxRows = Math.max(...[...byDepth.values()].map((c) => c.length));
  for (const [depth, col] of byDepth) {
    col.sort((a, b) => (inflow.get(b.address) ?? 0) - (inflow.get(a.address) ?? 0) || a.address.localeCompare(b.address));
    const top = ((maxRows - col.length) * ROW_H) / 2;
    els.push({
      group: "nodes",
      data: { id: `hdr-${depth}`, text: depth === 0 ? (col.length > 1 ? "VICTIMS" : "VICTIM") : `HOP ${depth}`, depth },
      position: { x: depth * COL_W, y: -ROW_H * 0.85 },
      classes: "hdr",
      selectable: false,
      grabbable: false,
    });
    col.forEach((n, i) => {
      const { dead, ...look } = nodeLook(n, freezesShown, swapped.has(n.address));
      els.push({
        group: "nodes",
        data: { id: n.address, depth, ...look },
        position: { x: depth * COL_W, y: top + i * ROW_H },
        classes: dead ? "dead" : "",
      });
    });
  }
  for (const e of trace.edges) {
    els.push({
      group: "edges",
      data: {
        // Token in the id: an ETH and a USDT flow between the same pair are two edges (M9).
        id: `${e.from}->${e.to}:${e.token}`,
        source: e.from,
        target: e.to,
        hop: e.hop,
        // Amount and confidence only; the method lives in the detail drawer.
        text: `${tok0(e.attributed_amount, e.token)}\n${pct(e.confidence)}`,
        // Thickness compares value, so non-USDT flows are converted at the trace's own swap rate.
        width: 1.5 + Math.log10(Math.max(e.attributed_amount * toUsdt(e.token), 10)) * 1.6,
      },
      classes: e.confidence < 0.6 ? "weak" : "",
    });
  }
  return els;
}

/** Fit the whole trail, but never below a zoom where labels are readable from across a room;
 *  when the trail is wider than the screen, start on the victim column and let the presenter pan. */
function fitReadable(cy: Core) {
  cy.fit(undefined, 40);
  if (cy.zoom() < 0.9) {
    cy.zoom(0.9);
    const first = cy.nodes('[depth = 0]');
    if (first.length) cy.center(first);
    // center() puts the victim column mid-screen; slide it to the left edge so the trail reads left to right.
    cy.panBy({ x: -(cy.width() / 2) + 170, y: 0 });
  }
}

/** Frame what the room should look at (frozen wallets, the exchange) with the flows around it.
 *  If the whole trail still reads at zoom 0.6 or more, show the whole trail instead. */
function fitFocus(cy: Core, ids: string[], animate: boolean) {
  const pad = 60;
  const all = cy.elements();
  const bb = all.boundingBox();
  const wholeZoom = Math.min((cy.width() - 2 * pad) / bb.w, (cy.height() - 2 * pad) / bb.h);
  let focus = cy.collection();
  for (const id of ids) focus = focus.union(cy.getElementById(id));
  const eles = wholeZoom >= 0.6 || focus.empty() ? all : focus.closedNeighborhood();
  cy.stop(true, false);
  if (animate) cy.animate({ fit: { eles, padding: pad }, duration: 600, easing: "ease-in-out-cubic" });
  else cy.fit(eles, pad);
}

const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const swapAddresses = (trace: Trace) => new Set((trace.swaps?.resolved ?? []).map((s) => s.address));

/** USDT per unit of a token, from the trace's resolved swaps (ETH only); 1 for USDT or when unknown. */
function usdtPerUnit(trace: Trace) {
  const sw = trace.swaps?.resolved ?? [];
  const eth = sw.reduce((s, x) => s + x.eth_out, 0);
  const rate = eth > 0 ? sw.reduce((s, x) => s + x.usdt_in, 0) / eth : 1;
  return (token: string) => (token === "ETH" ? rate : 1);
}

/** asOf: the case's story date (replay: the victim's report), used to say how long after it Tether froze. */
export default function TraceGraph({
  trace,
  asOf,
  onFreezesShown,
}: {
  trace: Trace;
  asOf?: string | null;
  /** Told whenever freezes are hidden or revealed, so the rest of the page can follow. */
  onFreezesShown?: (shown: boolean) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [shownHop, setShownHop] = useState(0);
  const maxHop = useMemo(() => Math.max(0, ...trace.edges.map((e) => e.hop)), [trace]);
  // Loops (DOJ ¶70's circular pattern) give some edges a hop number past the deepest column; label what's drawn.
  const maxDepth = useMemo(() => Math.max(0, ...trace.nodes.map((n) => n.depth)), [trace]);
  const hideFreezes = trace.method.freeze_visibility === "hidden";
  const [freezesShown, setFreezesShown] = useState(!hideFreezes);
  const frozen = useMemo(() => trace.nodes.filter((n) => n.frozen?.is_frozen && n.frozen.frozen_at), [trace]);
  const frozenIds = useMemo(() => trace.nodes.filter((n) => n.frozen?.is_frozen).map((n) => n.address), [trace]);
  // Live case: nothing to reveal, so the last hop frames the exchange (and any frozen wallet) instead.
  const liveFocus = useMemo(
    () => [...new Set([...trace.endpoints.filter((p) => p.reason === "exchange").map((p) => p.address), ...frozenIds])],
    [trace, frozenIds],
  );

  // Replay: freezes stay hidden until the presenter clicks "Reveal what Tether did" after the last hop (§0, AUDIT N1).

  useEffect(() => {
    onFreezesShown?.(freezesShown);
  }, [freezesShown, onFreezesShown]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const swapped = swapAddresses(trace);
    cy.batch(() => {
      for (const n of trace.nodes) {
        const { dead, ...look } = nodeLook(n, freezesShown, swapped.has(n.address));
        cy.getElementById(n.address).data(look).toggleClass("dead", dead);
      }
    });
  }, [trace, freezesShown]);

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
    if (hideFreezes) {
      setFreezesShown(false);
      writeFreezesShown(trace.trace_id, false);
    }
    reveal(0);
    let hop = 0;
    timer.current = setInterval(() => {
      hop += 1;
      reveal(hop);
      if (hop < maxHop) return;
      if (timer.current) clearInterval(timer.current);
      if (!hideFreezes && cyRef.current) fitFocus(cyRef.current, liveFocus, true);
    }, STEP_MS);
  }, [maxHop, reveal, hideFreezes, trace, liveFocus]);

  const revealFreezes = useCallback(() => {
    setFreezesShown(true);
    writeFreezesShown(trace.trace_id, true);
    if (cyRef.current) fitFocus(cyRef.current, frozenIds, !prefersReducedMotion());
  }, [trace, frozenIds]);

  const showAll = useCallback(() => {
    // Stop a running replay first, or its next tick would hide later hops again.
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    reveal(maxHop);
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
        elements: buildElements(trace, !hideFreezes),
        layout: { name: "preset", padding: 40 },
        minZoom: 0.5,
        maxZoom: 2.5,
        style: [
          {
            selector: "node",
            style: {
              shape: "round-rectangle",
              width: 232,
              height: 72,
              "border-width": 2.5,
              label: "data(text)",
              "text-wrap": "wrap",
              "text-valign": "center",
              "font-family": mono,
              "font-size": 16,
              "font-weight": 600,
              "line-height": 1.35,
              "transition-property": "opacity, background-color, border-color, color",
              "transition-duration": 600,
            },
          },
          // Colour mappings only where the data exists: column headers have none, and Cytoscape warns on them.
          {
            selector: "node[fill]",
            style: { "background-color": "data(fill)", "border-color": "data(color)", color: "data(ink)" },
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
              "font-size": 17,
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
              "font-size": 14,
              "font-weight": 600,
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
      fitReadable(cy);

      // Coming back after the reveal (e.g. from the packet): show the revealed trail at once, no replay (H8).
      if (hideFreezes && readFreezesShown(trace.trace_id)) {
        reveal(maxHop);
        setFreezesShown(true);
        fitFocus(cy, frozenIds, false);
      } else if (prefersReducedMotion()) reveal(maxHop);
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
  }, [trace, maxHop, play, reveal, hideFreezes, frozenIds]);

  const node = selected ? trace.nodes.find((n) => n.address === selected) ?? null : null;

  return (
    <section className={styles.wrap} aria-label="Money trail">
      <div className={styles.controls}>
        <span className={styles.progress}>
          {shownHop >= maxHop
            ? `Traced ${maxDepth} hops deep · ${trace.edges.length} money flows`
            : `Tracing step ${shownHop} of ${maxHop}…`}
        </span>
        <button type="button" onClick={play}>Replay trace</button>
        <button type="button" onClick={showAll} disabled={shownHop >= maxHop}>
          Show all hops
        </button>
        <button type="button" onClick={() => cyRef.current && fitReadable(cyRef.current)}>Fit to screen</button>
        <button type="button" onClick={() => cyRef.current?.fit(undefined, 40)}>Whole trail</button>
        {hideFreezes && !freezesShown && frozen.length > 0 && (
          <button
            type="button"
            className={styles.reveal}
            onClick={revealFreezes}
            disabled={shownHop < maxHop}
            title={shownHop < maxHop ? "Available once the last hop has unfolded" : undefined}
          >
            Reveal what Tether did
          </button>
        )}
      </div>
      {hideFreezes && freezesShown && frozen.length > 0 && (
        <p className={styles.freezeReveal} role="status">
          <strong>{freezeRevealText(frozen, asOf)}</strong>
          <span>Hound pointed at them from the victim&apos;s report alone.</span>
        </p>
      )}
      <ul className={styles.legend} aria-label="Legend">
        <li data-tone="victim">Victim</li>
        <li data-tone="trace">Intermediate wallet</li>
        <li data-tone="exchange">Exchange</li>
        <li data-tone="hold">Holding</li>
        <li data-tone="frozen">Tether froze this</li>
        <li data-tone="dead">Dead end</li>
        <li data-tone="weak">Under 60% confidence</li>
      </ul>
      {/* The detail drawer lives inside the stage so it never covers the toolbar or the reveal banner (review F8). */}
      <div className={styles.stage}>
        <div ref={box} className={styles.canvas} />
        {node && <NodeDetail trace={trace} node={node} freezesShown={freezesShown} onClose={() => setSelected(null)} />}
      </div>
    </section>
  );
}

function freezeRevealText(frozen: TraceNode[], asOf?: string | null) {
  const who = frozen.length === 1 ? "one of these wallets" : `${frozen.length} of these wallets`;
  if (!asOf) return `The engine never saw it: Tether later froze ${who}.`;
  const days = frozen.map((n) => daysBetween(asOf, n.frozen!.frozen_at!));
  const lo = Math.min(...days);
  const hi = Math.max(...days);
  const span = lo === hi ? `${lo} days` : `${lo} to ${hi} days`;
  return `The engine never saw it. Tether froze ${who} ${span} after the victim's report.`;
}
