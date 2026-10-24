"use client";

import { useEffect, useState } from "react";
import type { AuditEntry, Case, CaseSummary, Trace } from "@/lib/types";
import { shortAddr, tok0 } from "@/lib/format";
import { useTrace } from "@/lib/useTrace";
import Link from "next/link";
import CaseCard from "./CaseCard";
import OtherPayers from "./OtherPayers";
import TraceGraph from "./TraceGraph";
import styles from "./CaseView.module.css";

export default function CaseView({ c, initialTrace }: { c: CaseSummary | Case; initialTrace: Trace | null }) {
  const state = useTrace(c.case_id, initialTrace);
  const trace = state.phase === "done" ? state.trace : null;
  const asOf = "as_of" in c ? c.as_of : null;
  // Driven by the graph: a replay hides freezes until its last hop has unfolded.
  const [freezesShown, setFreezesShown] = useState(false);

  return (
    <>
      {trace && trace.status !== "done" && (
        <p className={styles.note} role="alert">
          Trace {trace.status === "partial" ? "stopped early (partial)" : "failed"}. What&apos;s shown is everything the engine
          reached; the endpoints say why each branch stopped.
        </p>
      )}
      {trace?.source === "fixture" && (
        <p className={styles.note} role="alert">
          The backend has no live chain adapters, so this replay ran on the committed example data, not live chain reads.
        </p>
      )}
      <main className={styles.layout}>
        <CaseCard c={c} trace={trace} freezesShown={freezesShown} />
        {state.phase === "done" && (
          <div className={styles.right}>
            <StatStrip trace={state.trace} freezesShown={freezesShown} />
            <TraceGraph trace={state.trace} asOf={asOf} onFreezesShown={setFreezesShown} />
            {/* Demo order: the trail first, then the twist (BRIEF §6). */}
            {freezesShown && (
              <>
                <OtherPayers trace={state.trace} />
                <AuditLog log={state.trace.audit_log} />
                <nav className={styles.next} aria-label="Next steps">
                  <Link href={`/cases/${encodeURIComponent(c.case_id)}/packet`} className={styles.primary}>
                    Open the detective packet
                  </Link>
                  <Link href="/exchange">Check an address at the exchange</Link>
                </nav>
              </>
            )}
          </div>
        )}
        {state.phase === "running" && <Progress log={state.log} startedAt={state.startedAt} />}
        {state.phase === "error" && (
          <div className={styles.panel} role="alert">
            <p className="eyebrow">The trace didn&apos;t finish</p>
            <p>{state.message}</p>
          </div>
        )}
      </main>
    </>
  );
}

/** The trail in four numbers, readable from the back of the room. Frozen count waits for the reveal. */
function StatStrip({ trace, freezesShown }: { trace: Trace; freezesShown: boolean }) {
  const wallets = trace.nodes.filter((n) => n.depth > 0).length;
  const hops = Math.max(0, ...trace.nodes.map((n) => n.depth));
  // What reached the places it stopped: endpoints count each victim dollar once (loop edges would double count).
  const reached = trace.endpoints.reduce((s, e) => s + (e.victim_inflow ?? 0), 0);
  const ends = trace.endpoints.length;
  const frozen = trace.nodes.filter((n) => n.frozen?.is_frozen).length;
  return (
    <ul className={styles.stats} aria-label="Trace summary">
      <li><b>{wallets}</b><span>wallets, {hops} hops</span></li>
      <li><b>{tok0(reached, "USDT")}</b><span>of the victim&apos;s money followed</span></li>
      <li><b>{ends}</b><span>places it stopped</span></li>
      {freezesShown && frozen > 0 && <li data-tone="frozen"><b>{frozen}</b><span>frozen by Tether</span></li>}
    </ul>
  );
}

/** Every step the engine took, for the investigator (Hyphenate: "would you hire it?"). Addresses shortened. */
function AuditLog({ log }: { log: AuditEntry[] }) {
  if (!log.length) return null;
  return (
    <details className={styles.audit}>
      <summary>Engine audit log: every step, {log.length} entries</summary>
      <ol className={styles.log}>
        {log.map((e, i) => (
          <li key={i} data-step={e.step}>
            <span className={styles.step}>{e.step.replaceAll("_", " ")}</span>
            {e.address && <span className="mono">{shortAddr(e.address)}</span>}
            <span className={styles.detail}>{e.detail.replace(/0x[0-9a-fA-F]{40,64}/g, shortAddr)}</span>
          </li>
        ))}
      </ol>
    </details>
  );
}

function Progress({ log, startedAt }: { log: AuditEntry[]; startedAt: number }) {
  const [now, setNow] = useState(startedAt);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const hops = log.filter((e) => e.step === "hop").length;

  return (
    <div className={styles.panel} role="status" aria-live="polite">
      <p className="eyebrow">Following the money · {Math.max(0, Math.round((now - startedAt) / 1000))} s</p>
      <p className={styles.lead}>
        {log.length ? `${log.length} steps so far, ${hops} hops expanded.` : "Starting the trace from the victim's sends…"}
      </p>
      {log.length > 0 && (
        <ol className={styles.log}>
          {log.slice(-10).map((e, i) => (
            <li key={`${e.t}-${log.length - 10 + i}`} data-step={e.step}>
              <span className={styles.step}>{e.step.replaceAll("_", " ")}</span>
              {e.address && <span className="mono">{shortAddr(e.address)}</span>}
              <span className={styles.detail}>{e.detail.replace(/0x[0-9a-fA-F]{40,64}/g, shortAddr)}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
