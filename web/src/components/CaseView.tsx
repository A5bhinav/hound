"use client";

import { useEffect, useState } from "react";
import type { AuditEntry, Case, CaseSummary, Endpoint, Trace } from "@/lib/types";
import { shortAddr, tok, tone, usdt } from "@/lib/format";
import { useTrace } from "@/lib/useTrace";
import Link from "next/link";
import CaseCard from "./CaseCard";
import OtherPayers from "./OtherPayers";
import TraceGraph from "./TraceGraph";
import styles from "./CaseView.module.css";

/* One job: watch the money move, then see where it stopped. The ribbons are the page; everything else is a short line
   or sits behind a disclosure (HIG layout › progressive disclosure, design principles › simplicity). */
export default function CaseView({ c, initialTrace }: { c: CaseSummary | Case; initialTrace: Trace | null }) {
  const state = useTrace(c.case_id, initialTrace);
  const trace = state.phase === "done" ? state.trace : null;
  const asOf = "as_of" in c ? c.as_of : null;
  // Driven by the graph: a replay hides freezes until its last hop has unfolded.
  const [freezesShown, setFreezesShown] = useState(false);
  const replay = trace?.replay ?? c.source === "doj_replay";

  return (
    <main className={styles.page}>
      <header className={styles.head}>
        <h1 className={styles.title}>{title(c)}</h1>
        <p className={styles.summary}>{summaryLine(c, replay)}</p>
      </header>

      {trace && trace.status !== "done" && (
        <p className={styles.note} role="alert">
          {trace.status === "partial" ? "Partial trace: some branches couldn't be fetched. Shown is everything reached." : "The trace failed."}
        </p>
      )}
      {trace?.source === "fixture" && (
        <p className={styles.note} role="alert">Offline: this replay ran on the committed example data.</p>
      )}

      {state.phase === "running" && <Progress log={state.log} startedAt={state.startedAt} />}
      {state.phase === "error" && (
        <div className={styles.panel} role="alert">
          <p className={styles.lead}>The trace didn&apos;t finish.</p>
          <p className={styles.detail}>{state.message}</p>
        </div>
      )}

      {trace && (
        <>
          <TraceGraph trace={trace} asOf={asOf} onFreezesShown={setFreezesShown} />
          {freezesShown && (
            <div className={styles.after}>
              <Stops trace={trace} freezesShown={freezesShown} />
              <OtherPayers trace={trace} />
            </div>
          )}
          {/* Always there once the trace is done: the demo comes back here to open the packet. */}
          {trace.endpoints.length === 0 ? (
            <p className={styles.noEnd} role="alert">
              Hound could not follow this payment anywhere, so there is no packet to write.{" "}
              {lastProblem(trace) ?? "Check the transaction hash and the amount, then trace again."}
            </p>
          ) : (
            <nav className={styles.next} aria-label="Next steps">
              <Link href={`/cases/${encodeURIComponent(c.case_id)}/packet`} className={styles.primary}>
                Open the packet
              </Link>
              <Link href="/exchange">Check an address</Link>
            </nav>
          )}
        </>
      )}

      <details className={styles.more}>
        <summary>Case details</summary>
        <CaseCard c={c} trace={trace} />
      </details>
      {trace && <AuditLog log={trace.audit_log} />}
      <p className={styles.footer}>Public chain data only. Reported, not proven. Hound never touches funds.</p>
    </main>
  );
}

/** "Victim A.H. (DOJ replay, US v. …)" reads as "Victim A.H."; the docket lives in the details. */
function title(c: CaseSummary | Case) {
  const a = c.victim?.alias ?? c.case_id;
  return a.includes(" (") ? a.slice(0, a.indexOf(" (")) : a;
}

function summaryLine(c: CaseSummary | Case, replay: boolean) {
  const sends = "sends" in c ? c.sends : [];
  const totals = new Map<string, number>();
  for (const s of sends) totals.set(s.token, (totals.get(s.token) ?? 0) + s.amount);
  const sent = [...totals].map(([t, n]) => tok(Math.round(n * 100) / 100, t)).join(" + ");
  const times = sends.map((s) => s.time).filter(Boolean).sort();
  const fmt = (t: string) => new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
  const when = times.length ? (times.length > 1 && fmt(times[0]) !== fmt(times[times.length - 1]) ? `${fmt(times[0])} to ${fmt(times[times.length - 1])}` : fmt(times[0])) : null;
  return [
    sends.length ? `${sends.length} ${sends.length === 1 ? "send" : "sends"} · ${sent}` : null,
    when,
    replay ? "Replay of a public DOJ case" : "Live case",
  ].filter(Boolean).join(" · ");
}

/** Where the victim's money ended, one quiet row per stop. Dust and pass-through residue stay in the details. */
function Stops({ trace, freezesShown }: { trace: Trace; freezesShown: boolean }) {
  const total = trace.endpoints.reduce((s, e) => s + (e.victim_inflow ?? 0), 0) || 1;
  const held = (p: Endpoint) => (p.reason === "exchange" || p.victim_remaining == null ? p.victim_inflow : p.victim_remaining);
  const rows = trace.endpoints
    .filter((p) => held(p) >= Math.max(1, total * 0.005) && p.reason !== "dust")
    .sort((a, b) => held(b) - held(a));
  if (!rows.length) return null;
  return (
    <section className={styles.stops} aria-labelledby="stops-h">
      <h2 id="stops-h" className={styles.h2}>Where it stopped</h2>
      <ul>
        {rows.map((p) => {
          const n = trace.nodes.find((x) => x.address === p.address);
          const t = n ? tone(n, freezesShown) : "trace";
          const frozenAt = freezesShown && n?.frozen?.is_frozen ? n.frozen.frozen_at : null;
          const status = frozenAt
            ? `Tether froze it ${new Date(frozenAt).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })}`
            : p.reason === "exchange"
              ? `At ${p.exchange ?? "an exchange"} · request ready`
              : p.reason === "holding"
                ? trace.replay ? "Holding at the cutoff" : "Still holding"
                : p.reason === "swap_unresolved" ? "Swap not followed" : p.reason.replaceAll("_", " ");
          return (
            <li key={p.address} data-tone={t}>
              <span className="mono">{n?.label ?? shortAddr(p.address)}</span>
              <span className={styles.status}>{status}</span>
              <span className={styles.amt}>{usdt(Math.round(held(p)))}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Every step the engine took, for the investigator. Addresses shortened. */
function AuditLog({ log }: { log: AuditEntry[] }) {
  if (!log.length) return null;
  return (
    <details className={styles.more}>
      <summary>Engine log · {log.length} steps</summary>
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
  const last = log[log.length - 1];
  return (
    <div className={styles.panel} role="status" aria-live="polite">
      <p className={styles.lead}>
        Following the money{log.length ? ` · ${hops} hops` : ""} · {Math.max(0, Math.round((now - startedAt) / 1000))} s
      </p>
      {last && (
        <p className={styles.detail}>
          {last.step.replaceAll("_", " ")} {last.address ? shortAddr(last.address) : ""}
        </p>
      )}
    </div>
  );
}

/** The engine's own words for why it stopped, for a judge who typed a wrong hash (AUDIT M1). */
function lastProblem(trace: Trace): string | null {
  const hit = [...trace.audit_log].reverse().find((e) => /error|fail|invalid|unresolved|no (usdt|send|transfer)|not found|budget|deadline/i.test(`${e.step} ${e.detail}`));
  if (!hit) return null;
  const words = hit.detail.replace(/0x[0-9a-fA-F]{40,64}/g, (m) => `${m.slice(0, 6)}…${m.slice(-4)}`);
  return words.endsWith(".") ? words : `${words}.`;
}
