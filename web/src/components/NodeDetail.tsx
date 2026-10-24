"use client";

import type { Chain, Trace, TraceEdge, TraceNode } from "@/lib/types";
import { KIND_LABEL, explorerUrl, pct, shortAddr, usdt } from "@/lib/format";
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

export default function NodeDetail({ trace, node, onClose }: { trace: Trace; node: TraceNode; onClose: () => void }) {
  const incoming = trace.edges.filter((e) => e.to === node.address);
  const outgoing = trace.edges.filter((e) => e.from === node.address);
  const endpoint = trace.endpoints.find((p) => p.address === node.address);

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
        <Ext href={explorerUrl(node.chain, "address", node.address)}>{node.address}</Ext>
      </p>

      {node.frozen?.is_frozen && (
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
        {endpoint && (
          <>
            <dt>Trail stops here</dt>
            <dd>
              {endpoint.reason.replace("_", " ")}
              {endpoint.exchange ? ` at ${endpoint.exchange}` : ""}
            </dd>
            <dt>Victim money in</dt>
            <dd>{usdt(endpoint.victim_inflow)}</dd>
            <dt>Freezable</dt>
            <dd>{endpoint.freezable ? "Yes, balance covers the victim's inflow" : "No"}</dd>
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
              {usdt(e.attributed_amount)} {side} <span className="mono">{shortAddr(e[side])}</span>
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
