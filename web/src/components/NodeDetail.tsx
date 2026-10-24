"use client";

import { useEffect } from "react";
import type { Chain, Trace, TraceEdge, TraceNode } from "@/lib/types";
import { KIND_LABEL, explorerUrl, pct, shortAddr, tok, usdt } from "@/lib/format";
import styles from "./TraceGraph.module.css";

function Ext({ href, children }: { href: string | null; children: React.ReactNode }) {
  return href ? (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  ) : (
    <>{children}</>
  );
}

export default function NodeDetail({
  trace,
  node,
  freezesShown,
  onClose,
}: {
  trace: Trace;
  node: TraceNode;
  freezesShown: boolean;
  onClose: () => void;
}) {
  const incoming = trace.edges.filter((e) => e.to === node.address);
  const outgoing = trace.edges.filter((e) => e.from === node.address);
  const endpoint = trace.endpoints.find((p) => p.address === node.address);
  const revealedFrozen = freezesShown && !!node.frozen?.is_frozen;
  // Live cases: no full address on a projected screen (§0, DEMO.md, review security-r2-4). Replays and wallets
  // Tether has frozen (a public on-chain record) are shown in full. Full addresses stay in the printed packet.
  const showFull = !!trace.replay || revealedFrozen;
  const hideFreezable = trace.method.freeze_visibility === "hidden" && !freezesShown;
  const swaps = (trace.swaps?.resolved ?? []).filter((s) => s.address === node.address);

  // Escape closes the drawer, like the × button (review F8).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside className={styles.detail} aria-label="Address details">
      <button type="button" className={styles.close} onClick={onClose} aria-label="Close details">
        ×
      </button>
      <p className="eyebrow">
        {KIND_LABEL[node.kind]} · hop {node.depth}
      </p>
      <h2 className={styles.detailTitle}>{node.label ?? shortAddr(node.address)}</h2>
      <p className="mono">
        {showFull ? (
          <Ext href={explorerUrl(node.chain, "address", node.address)}>{node.address}</Ext>
        ) : (
          `${shortAddr(node.address)} (live case, shortened on screen)`
        )}
      </p>

      {revealedFrozen && node.frozen && (
        <p className={styles.frozenBadge}>
          Tether froze this address{node.frozen.frozen_at ? ` on ${node.frozen.frozen_at.slice(0, 10)}` : ""}.
          {node.frozen.freeze_tx && (
            <>
              {" "}
              <Ext href={explorerUrl(node.chain, "tx", node.frozen.freeze_tx)}>Freeze transaction</Ext>
            </>
          )}
        </p>
      )}

      <dl className={styles.facts}>
        <dt>Balance</dt>
        <dd>{usdt(node.balance_usdt)}</dd>
        {endpoint && outgoing.length > 0 && (
          // The trace kept going from here; the endpoint is only what stayed behind (review F12).
          <>
            <dt>Left behind here</dt>
            <dd>
              {usdt(endpoint.victim_remaining ?? endpoint.victim_inflow)} residual ({endpoint.reason.replaceAll("_", " ")}), the rest moved on
            </dd>
          </>
        )}
        {endpoint && outgoing.length === 0 && (
          <>
            <dt>Trail stops here</dt>
            <dd>
              {endpoint.reason.replaceAll("_", " ")}
              {endpoint.exchange ? ` at ${endpoint.exchange}` : ""}
            </dd>
            <dt>Victim money in</dt>
            <dd>{usdt(endpoint.victim_inflow)}</dd>
            {endpoint.victim_remaining != null && (
              <>
                <dt>{trace.replay ? "Still here at cutoff" : "Still here"}</dt>
                <dd>{usdt(endpoint.victim_remaining)}</dd>
              </>
            )}
            {/* Before a replay's reveal, "No" would leak that Tether already froze it (review web-integration-8). */}
            {!hideFreezable && (
              <>
                <dt>Freezable</dt>
                <dd>
                  {revealedFrozen
                    ? "Already frozen by Tether"
                    : endpoint.freezable
                      ? "Yes, balance covers the victim's money"
                      : "No"}
                </dd>
              </>
            )}
          </>
        )}
        {node.label && (
          <>
            <dt>Label source</dt>
            <dd>{node.label_source ?? "case file"}</dd>
          </>
        )}
      </dl>

      {node.classifier && (
        <>
          <p className="eyebrow">Why we think it&apos;s {node.classifier.kind} ({pct(node.classifier.confidence)})</p>
          <ul className={styles.reasons}>
            {node.classifier.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </>
      )}

      {swaps.length > 0 && (
        <>
          <p className="eyebrow">Swapped ETH to USDT here</p>
          <ul className={styles.flows}>
            {swaps.map((s) => {
              const eth = Object.values(s.victim_eth).reduce((a, b) => a + b, 0);
              const usdtIn = Object.values(s.victim_usdt).reduce((a, b) => a + b, 0);
              return (
                <li key={s.tx_hash}>
                  <span>
                    Victim {tok(eth, "ETH")} → {tok(usdtIn, "USDT")}
                  </span>
                  <span className={styles.flowMeta}>{s.time.slice(0, 10)} · same transaction</span>
                  <span className="mono">
                    <Ext href={explorerUrl(node.chain, "tx", s.tx_hash)}>{shortAddr(s.tx_hash)}</Ext>
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      )}

      <Flows title="Money in" side="from" edges={incoming} chain={node.chain} />
      <Flows title="Money out" side="to" edges={outgoing} chain={node.chain} />
    </aside>
  );
}

function Flows({ title, side, edges, chain }: { title: string; side: "from" | "to"; edges: TraceEdge[]; chain: Chain }) {
  if (!edges.length) return null;
  return (
    <>
      <p className="eyebrow">{title}</p>
      <ul className={styles.flows}>
        {edges.map((e) => (
          <li key={`${e.from}${e.to}`}>
            <span>
              {tok(e.attributed_amount, e.token)} {side} <span className="mono">{shortAddr(e[side])}</span>
            </span>
            <span className={styles.flowMeta}>
              {pct(e.confidence)} · {e.method} · {e.tx_hashes.length} tx
            </span>
            {e.tx_hashes.slice(0, 5).map((h) => (
              <span key={h} className="mono">
                <Ext href={explorerUrl(chain, "tx", h)}>{shortAddr(h)}</Ext>
              </span>
            ))}
          </li>
        ))}
      </ul>
    </>
  );
}
