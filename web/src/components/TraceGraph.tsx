"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Trace, TraceEdge, TraceNode } from "@/lib/types";
import { KIND_LABEL, daysBetween, pct, shortAddr, tok0, tone, type Tone } from "@/lib/format";
import NodeDetail from "./NodeDetail";
import styles from "./TraceGraph.module.css";

/* Money-flow ribbons: columns are hops, ribbon width is victim money (USDT, each victim dollar counted once).
   Same data, gating and drawer as the old node graph; drawn as SVG so it is smooth, crisp and animatable. */

const STEP_MS = 900;
const NODE_W = 14;
const COL_GAP_MAX = 236;
const COL_GAP_MIN = 156;
const PAD_X = 26;
const PAD_TOP = 54;
const PAD_BOTTOM = 28;
const HEIGHT = 560;
const NODE_GAP = 22;
const LABEL_W = 150;
const MIN_NODE_H = 6;

type Placed = TraceNode & { x: number; y: number; h: number; value: number };
type Ribbon = { edge: TraceEdge; value: number; w: number; sy: number; ty: number; x0: number; x1: number };

/** USDT value of each seed: its USDT amount, or the USDT its ETH swapped into. Plus each ETH seed's swap rate. */
function seedCaps(trace: Trace) {
  const cap = new Map<string, number>();
  const eth = new Map<string, number>();
  for (const s of trace.seeds ?? []) {
    if (s.token === "USDT") cap.set(s.seed_id, (cap.get(s.seed_id) ?? 0) + s.amount);
    else eth.set(s.seed_id, (eth.get(s.seed_id) ?? 0) + s.amount);
  }
  for (const r of trace.swaps?.resolved ?? []) {
    for (const [sid, v] of Object.entries(r.victim_usdt ?? {})) cap.set(sid, (cap.get(sid) ?? 0) + v);
  }
  const sw = trace.swaps?.resolved ?? [];
  const ethOut = sw.reduce((s, x) => s + x.eth_out, 0);
  const avgRate = ethOut > 0 ? sw.reduce((s, x) => s + x.usdt_in, 0) / ethOut : 1;
  const rate = (sid: string) => {
    const e = eth.get(sid);
    const c = cap.get(sid);
    return e && c ? c / e : avgRate;
  };
  const total = [...cap.values()].reduce((a, b) => a + b, 0);
  return { cap, rate, avgRate, total };
}

/** An edge's victim money in USDT, each seed capped at its own value (loops re-cross the same edge). */
function edgeValue(e: TraceEdge, caps: ReturnType<typeof seedCaps>) {
  const isEth = e.token === "ETH";
  if (e.attributed_by_seed && caps.cap.size) {
    let v = 0;
    for (const [sid, amt] of Object.entries(e.attributed_by_seed)) {
      const usd = isEth ? amt * caps.rate(sid) : amt;
      const c = caps.cap.get(sid);
      v += c !== undefined ? Math.min(usd, c) : usd;
    }
    return v;
  }
  const usd = e.attributed_amount * (isEth ? caps.avgRate : 1);
  return caps.total ? Math.min(usd, caps.total) : usd;
}

function layout(trace: Trace, COL_GAP: number) {
  const caps = seedCaps(trace);
  const depth = new Map(trace.nodes.map((n) => [n.address, n.depth]));
  const forward: { edge: TraceEdge; value: number }[] = [];
  let loops = 0;
  for (const e of trace.edges) {
    const a = depth.get(e.from);
    const b = depth.get(e.to);
    if (a === undefined || b === undefined) continue;
    if (b <= a) {
      loops += 1; // money cycling back to an earlier wallet: counted by the engine, not drawn twice
      continue;
    }
    forward.push({ edge: e, value: edgeValue(e, caps) });
  }
  const inSum = new Map<string, number>();
  const outSum = new Map<string, number>();
  for (const f of forward) {
    inSum.set(f.edge.to, (inSum.get(f.edge.to) ?? 0) + f.value);
    outSum.set(f.edge.from, (outSum.get(f.edge.from) ?? 0) + f.value);
  }
  const maxDepth = Math.max(0, ...trace.nodes.map((n) => n.depth));
  const cols: TraceNode[][] = Array.from({ length: maxDepth + 1 }, () => []);
  for (const n of trace.nodes) cols[n.depth].push(n);
  const value = (a: string) => Math.max(inSum.get(a) ?? 0, outSum.get(a) ?? 0);

  // One scale for every column, so a ribbon's width means the same amount everywhere.
  const avail = HEIGHT - PAD_TOP - PAD_BOTTOM;
  const k = Math.min(
    ...cols
      .filter((c) => c.length)
      .map((c) => {
        const sum = c.reduce((s, n) => s + value(n.address), 0) || 1;
        return Math.max(0.0001, (avail - NODE_GAP * (c.length - 1) - MIN_NODE_H * c.length) / sum);
      }),
  );

  const placed = new Map<string, Placed>();
  cols.forEach((col, d) => {
    // Order by where their money comes from (fewer crossings), then by size.
    const center = (n: TraceNode) => {
      const ins = forward.filter((f) => f.edge.to === n.address && placed.has(f.edge.from));
      const w = ins.reduce((s, f) => s + f.value, 0);
      return w ? ins.reduce((s, f) => s + f.value * (placed.get(f.edge.from)!.y + placed.get(f.edge.from)!.h / 2), 0) / w : Infinity;
    };
    const sorted = [...col].sort((a, b) => center(a) - center(b) || value(b.address) - value(a.address));
    const hs = sorted.map((n) => Math.max(MIN_NODE_H, value(n.address) * k));
    const total = hs.reduce((a, b) => a + b, 0) + NODE_GAP * (sorted.length - 1);
    let y = PAD_TOP + Math.max(0, (avail - total) / 2);
    sorted.forEach((n, i) => {
      placed.set(n.address, { ...n, x: PAD_X + d * COL_GAP, y, h: hs[i], value: value(n.address) });
      y += hs[i] + NODE_GAP;
    });
  });

  // Stack ribbons on each node: outgoing ordered by target height, incoming by source height.
  const ribbons: Ribbon[] = forward
    .filter((f) => placed.has(f.edge.from) && placed.has(f.edge.to))
    .map((f) => {
      const s = placed.get(f.edge.from)!;
      const t = placed.get(f.edge.to)!;
      return { edge: f.edge, value: f.value, w: Math.max(1.5, f.value * k), sy: 0, ty: 0, x0: s.x + NODE_W, x1: t.x };
    });
  for (const n of placed.values()) {
    const outs = ribbons.filter((r) => r.edge.from === n.address).sort((a, b) => placed.get(a.edge.to)!.y - placed.get(b.edge.to)!.y);
    const ins = ribbons.filter((r) => r.edge.to === n.address).sort((a, b) => placed.get(a.edge.from)!.y - placed.get(b.edge.from)!.y);
    let y = n.y;
    for (const r of outs) { r.sy = y; y += r.w; }
    y = n.y;
    for (const r of ins) { r.ty = y; y += r.w; }
  }
  const width = PAD_X * 2 + maxDepth * COL_GAP + NODE_W + LABEL_W;
  return { nodes: [...placed.values()], ribbons, loops, maxDepth, width, total: caps.total };
}

const ribbonPath = (r: Ribbon) => {
  const xm = (r.x0 + r.x1) / 2;
  return `M${r.x0},${r.sy} C${xm},${r.sy} ${xm},${r.ty} ${r.x1},${r.ty} L${r.x1},${r.ty + r.w} C${xm},${r.ty + r.w} ${xm},${r.sy + r.w} ${r.x0},${r.sy + r.w} Z`;
};

const NODE_FILL: Record<Tone | "victim", string> = {
  victim: "var(--eth)",
  trace: "var(--trace)",
  exchange: "var(--exchange)",
  hold: "var(--hold)",
  frozen: "var(--ice)",
  dead: "var(--dead)",
};

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
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  // Columns spread to fill the panel (so the last hop and its labels fit on a projector), never tighter than readable.
  const scrollRef = useRef<HTMLDivElement>(null);
  const [boxW, setBoxW] = useState(1100);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setBoxW(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const depthMax = useMemo(() => Math.max(1, ...trace.nodes.map((n) => n.depth)), [trace]);
  const colGap = Math.max(COL_GAP_MIN, Math.min(COL_GAP_MAX, (boxW - PAD_X * 2 - NODE_W - LABEL_W) / depthMax));
  const lay = useMemo(() => layout(trace, colGap), [trace, colGap]);
  const maxHop = lay.maxDepth;
  const [shownHop, setShownHop] = useState(0);
  const hideFreezes = trace.method.freeze_visibility === "hidden";
  const [freezesShown, setFreezesShown] = useState(!hideFreezes);
  const frozen = useMemo(() => trace.nodes.filter((n) => n.frozen?.is_frozen && n.frozen.frozen_at), [trace]);
  const swapped = useMemo(() => new Set((trace.swaps?.resolved ?? []).map((s) => s.address)), [trace]);

  // Replay: freezes stay hidden until the presenter clicks "Reveal what Tether did" after the last hop (§0, AUDIT N1).
  useEffect(() => {
    onFreezesShown?.(freezesShown);
  }, [freezesShown, onFreezesShown]);

  const play = useCallback(() => {
    if (timer.current) clearInterval(timer.current);
    if (hideFreezes) setFreezesShown(false);
    setShownHop(0);
    let hop = 0;
    timer.current = setInterval(() => {
      hop += 1;
      setShownHop(hop);
      if (hop >= maxHop && timer.current) clearInterval(timer.current);
    }, STEP_MS);
  }, [maxHop, hideFreezes]);

  const showAll = useCallback(() => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    setShownHop(maxHop);
  }, [maxHop]);

  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Start on the next tick: reduced motion shows every hop at once, otherwise the hops unfold.
    const t = setTimeout(() => (reduced ? setShownHop(maxHop) : play()), 0);
    return () => {
      clearTimeout(t);
      if (timer.current) clearInterval(timer.current);
    };
  }, [play, maxHop]);

  const node = selected ? trace.nodes.find((n) => n.address === selected) ?? null : null;
  const lookOf = (n: TraceNode) => {
    const t = tone(n, freezesShown);
    const victim = n.kind === "victim" || (n.depth === 0 && t === "trace");
    const sub = freezesShown && n.frozen?.is_frozen
      ? "Tether froze this"
      : victim ? "Victim" : swapped.has(n.address) ? "Swap ETH → USDT" : KIND_LABEL[n.kind];
    return { fill: NODE_FILL[victim ? "victim" : t], sub, tone: victim ? "victim" : t };
  };
  const ribbonFill = (r: Ribbon) => {
    if (r.edge.token === "ETH") return "var(--eth)";
    const to = trace.nodes.find((n) => n.address === r.edge.to);
    const t = to ? tone(to, freezesShown) : "trace";
    return t === "frozen" ? "url(#rb-seal)" : t === "exchange" ? "var(--exchange)" : t === "hold" ? "var(--hold)" : "var(--trace)";
  };
  const depthOf = (a: string) => lay.nodes.find((n) => n.address === a)?.depth ?? 0;
  // Where the money stopped (meaningful amounts only): these keep a permanent label.
  const stops = new Set(trace.endpoints.filter((e) => (e.victim_inflow ?? 0) >= Math.max(100, lay.total * 0.005)).map((e) => e.address));
  // Only the colours on screen get a legend entry.
  const tones = new Set(trace.nodes.map((n) => tone(n, freezesShown)));
  const legend = (
    [
      ["victim", trace.edges.some((e) => e.token === "ETH") ? "Her ETH" : "Victim"],
      ["trace", "USDT moving"],
      ["exchange", "At an exchange"],
      ["hold", "Holding"],
      ["frozen", "Tether froze it"],
      ["dead", "Dead end"],
    ] as const
  ).filter(([t]) => t === "victim" || t === "trace" || tones.has(t));

  return (
    <section className={styles.wrap} aria-label="Money trail">
      <div className={styles.controls}>
        <span className={styles.progress} aria-live="polite">
          {shownHop < maxHop ? `Hop ${shownHop} of ${maxHop}` : "Width = victim money"}
        </span>
        {shownHop < maxHop ? (
          <button type="button" onClick={showAll}>Skip to the end</button>
        ) : (
          <button type="button" onClick={play}>Replay</button>
        )}
        {hideFreezes && !freezesShown && frozen.length > 0 && (
          <button
            type="button"
            className={styles.reveal}
            onClick={() => setFreezesShown(true)}
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
      <div className={styles.stage}>
        <div className={styles.scroller} ref={scrollRef}>
          <svg
            className={styles.flow}
            width={lay.width}
            height={HEIGHT}
            viewBox={`0 0 ${lay.width} ${HEIGHT}`}
            role="img"
            aria-label={`Money flow over ${maxHop} hops: ${lay.nodes.length} wallets, ribbon width is victim money`}
          >
            <defs>
              {/* Frozen funds are drawn sealed: a diagonal hatch, like a redacted exhibit. Everything else is a flat fill. */}
              <pattern id="rb-seal" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <rect width="7" height="7" fill="var(--ice)" fillOpacity="0.22" />
                <line x1="0" y1="0" x2="0" y2="7" stroke="var(--ice)" strokeWidth="2.6" />
              </pattern>
            </defs>

            {Array.from({ length: maxHop + 1 }, (_, d) => (
              <text key={`h${d}`} x={PAD_X + d * colGap} y={24} className={styles.colHead} data-on={d <= shownHop}>
                {d === 0 ? "Victim" : `Hop ${d}`}
              </text>
            ))}

            {lay.ribbons.map((r) => {
              const id = `${r.edge.from}->${r.edge.to}`;
              const on = depthOf(r.edge.to) <= shownHop;
              const dim = hover && hover !== r.edge.from && hover !== r.edge.to;
              return (
                <path
                  key={id}
                  d={ribbonPath(r)}
                  fill={ribbonFill(r)}
                  className={styles.ribbon}
                  data-on={on}
                  data-dim={!!dim}
                  data-weak={r.edge.confidence < 0.6}
                >
                  <title>{`${shortAddr(r.edge.from)} → ${shortAddr(r.edge.to)}: ${tok0(r.edge.attributed_amount, r.edge.token)} (${tok0(r.value, "USDT")} of victim money) · ${pct(r.edge.confidence)} · ${r.edge.method}`}</title>
                </path>
              );
            })}

            {lay.nodes.map((n) => {
              const look = lookOf(n);
              const on = n.depth <= shownHop;
              const name = n.label ?? shortAddr(n.address);
              const cy = n.y + n.h / 2;
              const showLabel = n.depth === 0 || stops.has(n.address) || hover === n.address || selected === n.address;
              return (
                <g
                  key={n.address}
                  className={styles.node}
                  data-on={on}
                  data-tone={look.tone}
                  data-selected={selected === n.address}
                  role="button"
                  tabIndex={on ? 0 : -1}
                  aria-label={`${name}, ${look.sub}${n.value >= 1 ? `, ${tok0(n.value, "USDT")} of victim money` : ""}. Open details`}
                  onMouseEnter={() => setHover(n.address)}
                  onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover(n.address)}
                  onBlur={() => setHover(null)}
                  onClick={() => on && setSelected(n.address)}
                  onKeyDown={(ev) => {
                    if (on && (ev.key === "Enter" || ev.key === " ")) {
                      ev.preventDefault();
                      setSelected(n.address);
                    }
                  }}
                >
                  <rect x={n.x - 6} y={n.y - 6} width={NODE_W + 12} height={n.h + 12} fill="transparent" />
                  <rect x={n.x} y={n.y} width={NODE_W} height={n.h} rx={2} fill={look.tone === "frozen" ? "url(#rb-seal)" : look.fill} stroke={look.tone === "frozen" ? "var(--ice)" : "none"} strokeWidth={1.5} />
                  {showLabel && (
                    <>
                      {/* The victim's label sits above her bar, off the ribbons; every other label to the right of its wallet. */}
                      <text x={n.depth === 0 ? n.x : n.x + NODE_W + 8} y={n.depth === 0 ? n.y - 26 : cy - 4} className={styles.nodeAmt}>{n.value >= 1 ? tok0(n.value, "USDT") : name}</text>
                      <text x={n.depth === 0 ? n.x : n.x + NODE_W + 8} y={n.depth === 0 ? n.y - 10 : cy + 13} className={styles.nodeSub} data-tone={look.tone}>
                        {look.tone === "frozen" ? "Tether froze it" : look.tone === "exchange" ? (n.label ?? "Exchange") : n.depth === 0 ? "Victim" : name}
                      </text>
                    </>
                  )}
                </g>
              );
            })}
          </svg>
        </div>
        {node && <NodeDetail trace={trace} node={node} freezesShown={freezesShown} onClose={() => setSelected(null)} />}
      </div>
      <ul className={styles.legend} aria-label="Legend">
        {legend.map(([t, label]) => (
          <li key={t} data-tone={t}>{label}</li>
        ))}
      </ul>
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
