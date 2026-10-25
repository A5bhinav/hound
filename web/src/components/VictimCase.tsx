"use client";

import Link from "next/link";
import { useTrace } from "@/lib/useTrace";
import { explorerUrl, shortAddr, tok, usdt } from "@/lib/format";
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
  const state = useTrace(caseId, null, code);
  const report = `/cases/${encodeURIComponent(caseId)}/packet?audience=victim&code=${encodeURIComponent(code)}`;

  if (state.phase === "running") {
    return (
      <section className="box" role="status">
        <p className={styles.status}>
          <span className="badge badge-hold">Working</span> We are following your money now. Keep this page open.
        </p>
        <p className="small">This usually takes under a minute.</p>
      </section>
    );
  }
  if (state.phase === "error") {
    return (
      <section className="box" role="alert">
        <p className={styles.error}>We couldn&apos;t finish following your money just now.</p>
        <ul className="checks" style={{ marginTop: "1rem" }}>
          <li>Please reload this page in a minute</li>
          <li>Your case is saved under code {code}</li>
        </ul>
      </section>
    );
  }

  const trace = state.trace;
  const s = stops(trace);
  const exchanges = [...s.exchanges];
  const followed = trace.endpoints.reduce((n, p) => n + (p.victim_inflow ?? 0), 0);
  // The agent stores "unknown" when the caller didn't say, or sent the money inside the scam app itself.
  const exchange = exchangeUsed && !/^(unknown|none|n\/?a|not sure|-)$/i.test(exchangeUsed.trim()) ? exchangeUsed : null;
  return (
    <>
      {trace.endpoints.length > 0 && (
        <div className={`grid g3 ${styles.tiles}`}>
          <div className="box">
            <p className="label">Money followed</p>
            <span className="stat-n">{usdt(followed)}</span>
          </div>
          <div className="box">
            <p className="label">Wallets it passed</p>
            <span className="stat-n">{Math.max(0, trace.nodes.length - 1)}</span>
          </div>
          <div className="box">
            <p className="label">Your case code</p>
            <span className="stat-n">{code}</span>
          </div>
        </div>
      )}

      {trace.seeds.length > 0 && (
        // Ties the result to what the victim uploaded: the exact payment Hound found on chain and followed from.
        <section className={`box ${styles.paid}`} aria-labelledby="paid-h">
          <h2 id="paid-h" className={styles.boxTitle}>
            Your payment
          </h2>
          <ul className={styles.paidList}>
            {trace.seeds.map((p) => (
              <li key={p.seed_id}>
                <strong>{tok(p.amount, p.token)}</strong>
                <span className="mono">tx {shortAddr(p.tx_hash)}</span>
                <Verify href={explorerUrl(trace.nodes[0]?.chain ?? "ethereum", "tx", p.tx_hash)} />
              </li>
            ))}
          </ul>
          <p className="small">
            This is the payment from your screenshot. We found it on the blockchain and followed the money from there.
          </p>
        </section>
      )}

      <div className={`grid g2 ${styles.big}`}>
        <section className="box" aria-labelledby="found-h">
          <div className="box-h">
            <h2 id="found-h">What we found</h2>
            <span className="badge">Reported, not proven</span>
          </div>
          {trace.endpoints.length === 0 ? (
            <ul className="checks">
              <li>We could not follow this payment anywhere yet</li>
              <li>Check that the screenshot shows the right payment</li>
              <li>
                Then <Link href={`/c/${code}`}>send it again</Link>
              </li>
            </ul>
          ) : (
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
          )}
          {trace.endpoints.length > 0 && (
            // Each wallet the money reached, so a victim (or a judge) can check every one on a public explorer.
            <>
              <h3 className={styles.subTitle}>Where your money is now</h3>
              <ul className={styles.wallets}>
                {[...trace.endpoints]
                  .filter((p) => (p.victim_inflow ?? 0) >= 1)
                  .sort((a, b) => (b.victim_inflow ?? 0) - (a.victim_inflow ?? 0))
                  .slice(0, 6)
                  .map((p) => (
                    <li key={p.address}>
                      <span className="mono">{shortAddr(p.address)}</span>
                      <span>{WHERE[p.reason] ?? (p.exchange ? `Reached ${p.exchange}` : "Still moving")}</span>
                      <strong>{usdt(p.reason === "exchange" || p.victim_remaining == null ? p.victim_inflow : p.victim_remaining)}</strong>
                      <Verify href={explorerUrl(trace.nodes[0]?.chain ?? "ethereum", "address", p.address)} />
                    </li>
                  ))}
              </ul>
            </>
          )}
          <div className={styles.actions}>
            <Link href={report} className={`btn btn-primary btn-lg ${styles.primary}`}>
              Open your report (print or save as PDF) →
            </Link>
          </div>
        </section>

        <section className="box" aria-labelledby="todo-h">
          <h2 id="todo-h" className={styles.boxTitle}>What to do now</h2>
          <ol className={styles.todo}>
            <li>
              Report it to the FBI at <a href="https://www.ic3.gov" target="_blank" rel="noreferrer">ic3.gov</a>.
              <span>Attach your Hound report. It lists every wallet and who to contact.</span>
            </li>
            <li>
              Tell {exchange || "the app or exchange you sent the money from"} that it was a scam.
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
        </section>
      </div>

      {trace.endpoints.length > 0 && (
        <details className={`box ${styles.trail}`}>
          <summary>See the trail your money took</summary>
          <TraceGraph trace={trace} />
        </details>
      )}
    </>
  );
}

const WHERE: Record<string, string> = {
  frozen: "Frozen by Tether",
  holding: "Sitting here, can be frozen",
  exchange: "Reached an exchange",
};

/** Opens the transfer on a public block explorer, so anyone can check it independently of Hound. */
function Verify({ href }: { href: string | null }) {
  if (!href) return null;
  return (
    <a href={href} target="_blank" rel="noreferrer" className={styles.verify}>
      Verify on Etherscan ↗
    </a>
  );
}
