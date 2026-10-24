"use client";

import Link from "next/link";
import { useTrace } from "@/lib/useTrace";
import { usdt } from "@/lib/format";
import type { Endpoint, Trace } from "@/lib/types";
import styles from "@/app/victim.module.css";
import TraceGraph from "./TraceGraph";

/** Where a victim's money ended, grouped by what they can do about it. */
function stops(trace: Trace) {
  const frozenAt = new Set(trace.nodes.filter((n) => n.frozen?.is_frozen).map((n) => n.address));
  const held = (p: Endpoint) => (p.reason === "exchange" || p.victim_remaining == null ? p.victim_inflow : p.victim_remaining);
  const out = { frozen: 0, exchanges: new Map<string, number>(), freezable: 0, other: 0 };
  for (const p of trace.endpoints) {
    const v = held(p) ?? 0;
    if (p.reason === "frozen" || frozenAt.has(p.address)) out.frozen += v;
    else if (p.reason === "exchange") out.exchanges.set(p.exchange || "an exchange", (out.exchanges.get(p.exchange || "an exchange") ?? 0) + v);
    else if (p.reason === "holding" || p.freezable) out.freezable += v;
    else out.other += v;
  }
  return out;
}

/** The victim's own case: what Hound found, in plain words, and what to do now. */
export default function VictimCase({ caseId, code, exchangeUsed }: { caseId: string; code: string; exchangeUsed?: string | null }) {
  const state = useTrace(caseId, null);
  const report = `/cases/${encodeURIComponent(caseId)}/packet?audience=victim&code=${encodeURIComponent(code)}`;

  if (state.phase === "running") {
    return (
      <p className={styles.status} role="status">
        We are following your money now. This usually takes under a minute; keep this page open.
      </p>
    );
  }
  if (state.phase === "error") {
    return (
      <p className={styles.error} role="alert">
        We couldn&apos;t finish following your money just now. Please reload this page in a minute. Your case is saved under code{" "}
        {code}.
      </p>
    );
  }

  const trace = state.trace;
  const s = stops(trace);
  const exchanges = [...s.exchanges];
  const followed = trace.endpoints.reduce((n, p) => n + (p.victim_inflow ?? 0), 0);
  return (
    <>
      <h2 className={styles.h2}>What we found</h2>
      {trace.endpoints.length === 0 ? (
        <p className={styles.status}>
          We could not follow this payment anywhere yet. Check that the screenshot shows the right payment, then{" "}
          <Link href={`/c/${code}`}>send it again</Link>.
        </p>
      ) : (
        <>
          <p>
            We followed {usdt(followed)} of your money through {Math.max(0, trace.nodes.length - 1)} wallets. This is where it
            went. Reported, not proven.
          </p>
          <ul className={styles.found}>
            {s.frozen > 0 && (
              <li>
                Frozen by Tether, so it can&apos;t move <strong>{usdt(s.frozen)}</strong>
              </li>
            )}
            {exchanges.map(([name, v]) => (
              <li key={name}>
                Reached {name}, which can freeze the account it went to <strong>{usdt(v)}</strong>
              </li>
            ))}
            {s.freezable > 0 && (
              <li>
                Sitting in wallets Tether can freeze on a police request <strong>{usdt(s.freezable)}</strong>
              </li>
            )}
            {s.other > 0 && (
              <li>
                Moved on where we could not follow it further <strong>{usdt(s.other)}</strong>
              </li>
            )}
          </ul>
        </>
      )}

      <h2 className={styles.h2}>What to do now</h2>
      <ol className={styles.todo}>
        <li>
          Report it to the FBI at <a href="https://www.ic3.gov" target="_blank" rel="noreferrer">ic3.gov</a>.
          <span>Attach your Hound report below. It lists every wallet and who to contact.</span>
        </li>
        <li>
          Tell {exchangeUsed || "the exchange you sent the money from"} that it was a scam.
          <span>Give them your case code, {code}, and the report.</span>
        </li>
        {(exchanges.length > 0 || s.freezable > 0) && (
          <li>
            Ask your local police to send a freeze request.
            <span>
              {exchanges.length > 0 ? `${exchanges.map(([n]) => n).join(" and ")} can freeze the account your money reached. ` : ""}
              {s.freezable > 0 ? "Tether can freeze USDT on one law enforcement request." : ""}
            </span>
          </li>
        )}
        <li>
          Stop sending money to the platform, even if it asks for a fee or a tax to release your funds.
          <span>Don&apos;t pay anyone who offers to recover your money for a fee. That is a second scam.</span>
        </li>
        <li>
          Keep your case code, {code}.
          <span>
            It opens this page again: <Link href={`/my/${code}`}>/my/{code}</Link>
          </span>
        </li>
      </ol>
      <Link href={report} className={styles.primary}>
        Open your report (print or save as PDF) →
      </Link>

      {trace.endpoints.length > 0 && (
        <details className={styles.trail}>
          <summary>See the trail your money took</summary>
          <TraceGraph trace={trace} />
        </details>
      )}
    </>
  );
}
