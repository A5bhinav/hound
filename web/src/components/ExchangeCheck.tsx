"use client";

import { useEffect, useRef, useState } from "react";
import { explorerUrl, pct, shortAddr, tok, usdt } from "@/lib/format";
import type { Chain } from "@/lib/types";
import styles from "./ExchangeCheck.module.css";

interface CheckResult {
  decision: "allow" | "warn" | "hold";
  reasons: string[];
  confidence: number;
  evidence: {
    rule_fired?: string;
    case_ids?: string[];
    label?: { name: string; kind: string; exchange?: string } | null;
    path?: { from: string; to: string; amount: number; token?: string; tx_hashes: string[]; confidence: number; method: string }[];
    victim_inflow_usdt?: number;
    frozen?: { is_frozen: boolean; frozen_at: string | null; freeze_tx: string | null } | null;
    watchlist_version?: string;
  };
}

type Phase =
  | { k: "form" }
  | { k: "checking" }
  | { k: "result"; r: CheckResult; address: string; chain: Chain; amount: number }
  | { k: "error"; message: string };

// Demo shortcuts: a wallet from the DOJ replay trace, and a labelled exchange hot wallet.
const SAMPLES: { label: string; chain: Chain; address: string }[] = [
  { label: "A wallet from the DOJ case (on the warning list)", chain: "ethereum", address: "0xa1770ead287dc8e91631a7a323390d5b744f0021" },
  { label: "An exchange hot wallet", chain: "ethereum", address: "0x28c6c06298d514db089934071355e5743bf21d60" },
];

const HEADLINE = {
  hold: "Withdrawal held",
  warn: "Check before you send",
  allow: "Withdrawal sent",
} as const;

export default function ExchangeCheck() {
  const [chain, setChain] = useState<Chain>("ethereum");
  const [address, setAddress] = useState("");
  const [amount, setAmount] = useState("2500");
  const [phase, setPhase] = useState<Phase>({ k: "form" });
  const amountClean = amount.replace(/[,\s_]/g, "").trim(); // "1,000" and "2 500" are fine
  const amountN = Number(amountClean);
  const amountOk = /^\d+(\.\d+)?$/.test(amountClean) && amountN > 0; // plain decimals only, no 0x10 or 1e3
  // After Withdraw the verdict can sit below the fold (phone, 720p projector): bring it to the middle of the screen.
  const sideRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (phase.k !== "result" && phase.k !== "error") return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // The verdict row (badge + headline), not the whole result box, which can be taller than the screen.
    const verdict = sideRef.current?.querySelector("[data-decision]")?.firstElementChild;
    verdict?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
  }, [phase]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!amountOk) return;
    setPhase({ k: "checking" });
    const url = `/api/check?chain=${chain}&address=${encodeURIComponent(address.trim())}`;
    try {
      const res = await fetch(url, { cache: "no-store" });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        const detail = body && typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`;
        const hint = res.status >= 500 ? " Is the backend running at HOUND_API_URL?" : "";
        return setPhase({ k: "error", message: `${detail}${hint}` });
      }
      setPhase({ k: "result", r: body as CheckResult, address: address.trim(), chain, amount: amountN });
    } catch (err) {
      console.error("[hound-web] check failed:", err);
      setPhase({ k: "error", message: `Couldn't reach the web server: ${err}` });
    }
  }

  return (
    <div className={styles.page}>
      <section className={`box ${styles.how}`} aria-labelledby="how-h">
        <h2 id="how-h" className={styles.howTitle}>How the check works</h2>
        <ol className={styles.steps}>
          <li>
            <span className={styles.stepN}>1</span>
            <span>Every wallet Hound traced goes on a warning list</span>
          </li>
          <li>
            <span className={styles.stepN}>2</span>
            <span>Before a withdrawal leaves, the exchange asks Hound</span>
          </li>
          <li>
            <span className={styles.stepN}>3</span>
            <span>Hound answers hold, warn or allow, with its evidence</span>
          </li>
          <li>
            <span className={styles.stepN}>4</span>
            <span>The exchange decides. Hound never holds funds</span>
          </li>
        </ol>
        <p className="label">Answers</p>
        <dl className={`kv ${styles.answers}`}>
          <dt><span className="badge badge-red">Hold</span></dt>
          <dd>On the warning list: payment stays in the account</dd>
          <dt><span className="badge badge-hold">Warn</span></dt>
          <dd>Linked to reported scam activity: confirm first</dd>
          <dt><span className="badge badge-ok">Allow</span></dt>
          <dd>No Hound warning, which is not proof it is safe</dd>
        </dl>
        <p className={`small ${styles.howFoot}`}>Reported, not proven.</p>
      </section>

      <div className={styles.exchange}>
        <header className={styles.exHead}>
          <span className={styles.exName}>Demo Exchange</span>
          <span className={styles.exTag}>Example withdrawal screen · checks Hound before sending</span>
        </header>

        <div className={styles.exBody}>
          <form className={styles.form} onSubmit={submit}>
            <h2 className={styles.title}>Withdraw USDT</h2>
            <label className={styles.field}>
              <span>Network</span>
              <select value={chain} onChange={(e) => setChain(e.target.value as Chain)}>
                <option value="ethereum">Ethereum (ERC-20)</option>
                <option value="tron">Tron (TRC-20)</option>
              </select>
            </label>
            <label className={styles.field}>
              <span>Destination address</span>
              <input
                required
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                placeholder={chain === "ethereum" ? "0x…" : "T…"}
                spellCheck={false}
                autoComplete="off"
                className="mono"
              />
            </label>
            <label className={styles.field}>
              <span>Amount (USDT)</span>
              <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" aria-invalid={!amountOk} />
              {!amountOk && <span role="alert" className={styles.fieldErr}>Enter an amount above 0.</span>}
            </label>
            <button type="submit" className={styles.send} disabled={phase.k === "checking" || !address.trim() || !amountOk}>
              {phase.k === "checking" ? "Checking destination…" : "Withdraw"}
            </button>
            <div className={styles.samples}>
              <span>Try:</span>
              {SAMPLES.map((s) => (
                <button
                  key={s.address}
                  type="button"
                  onClick={() => {
                    setChain(s.chain);
                    setAddress(s.address);
                    setPhase({ k: "form" });
                  }}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </form>

          <div className={styles.side} ref={sideRef}>
            {(phase.k === "form" || phase.k === "checking") && (
              <div className={styles.idle}>
                <p className="label">Destination check</p>
                <p className={styles.idleTitle}>{phase.k === "checking" ? "Asking Hound…" : "No withdrawal yet"}</p>
                <ul className="checks">
                  <li>Pick a wallet under Try:</li>
                  <li>Press Withdraw</li>
                  <li>The exchange&apos;s answer shows here</li>
                </ul>
              </div>
            )}
            {phase.k === "error" && (
              <div className={styles.result} data-decision="error" role="alert">
                <span className="badge badge-red">Error</span>
                <p className={styles.verdict}>Couldn&apos;t check this address</p>
                <p className={styles.lede}>{phase.message}</p>
              </div>
            )}
            {phase.k === "result" && <Result r={phase.r} address={phase.address} chain={phase.chain} amount={phase.amount} />}
          </div>
        </div>
      </div>
    </div>
  );
}

const BADGE = {
  hold: ["badge-red", "Hold"],
  warn: ["badge-hold", "Warn"],
  allow: ["badge-ok", "Allow"],
} as const;

function Result({ r, address, chain, amount }: { r: CheckResult; address: string; chain: Chain; amount: number }) {
  const ev = r.evidence;
  const [badge, word] = BADGE[r.decision];
  return (
    <div className={styles.result} data-decision={r.decision} role={r.decision === "allow" ? "status" : "alert"}>
      <div className={styles.verdictRow}>
        <span className={`badge ${badge}`}>Hound: {word}</span>
        <span className={styles.conf}>Confidence {pct(r.confidence)}</span>
      </div>
      <p className={styles.verdict}>{HEADLINE[r.decision]}</p>
      <ul className={`checks ${styles.lede}`}>
        {r.decision === "hold" && (
          <>
            <li>Your {usdt(amount)} has not left your account</li>
            <li>This address is part of a traced scam cluster</li>
          </>
        )}
        {r.decision === "warn" && (
          <>
            <li>This address is linked to reported scam activity</li>
            <li>Confirm you know who you&apos;re paying before you send</li>
          </>
        )}
        {r.decision === "allow" && (
          <>
            <li>No Hound warning for this address</li>
            <li>That doesn&apos;t prove it&apos;s safe</li>
          </>
        )}
      </ul>
      {r.reasons.length > 0 && (
        <>
          <p className="label">Why</p>
          <ul className={`checks ${styles.reasons}`}>
            {r.reasons.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </>
      )}

      {r.decision !== "allow" && (
        <details className={styles.evidence} open={r.decision === "hold"}>
          <summary>Evidence for the exchange&apos;s fraud team</summary>
          <dl className={`kv ${styles.evKv}`}>
            <dt>Address</dt>
            <dd className="mono">{address}</dd>
            {ev.rule_fired && (
              <>
                <dt>Rule</dt>
                <dd className="mono">{ev.rule_fired}</dd>
              </>
            )}
            <dt>Confidence</dt>
            <dd>{pct(r.confidence)}</dd>
            {ev.case_ids && ev.case_ids.length > 0 && (
              <>
                <dt>Traced from</dt>
                <dd className="mono">{ev.case_ids.join(", ")}</dd>
              </>
            )}
            {ev.victim_inflow_usdt != null && ev.victim_inflow_usdt > 0 && (
              <>
                <dt>Victim money in</dt>
                <dd>{usdt(ev.victim_inflow_usdt)}</dd>
              </>
            )}
            {ev.frozen?.is_frozen && (
              <>
                <dt>Tether freeze</dt>
                <dd>
                  <span className="badge badge-ice">Frozen {ev.frozen.frozen_at?.slice(0, 10) ?? "date unknown"}</span>
                  {ev.frozen.freeze_tx && (
                    <>
                      {" "}
                      <a href={explorerUrl(chain, "tx", ev.frozen.freeze_tx) ?? undefined} target="_blank" rel="noreferrer" className="mono">
                        {shortAddr(ev.frozen.freeze_tx)}
                      </a>
                    </>
                  )}
                </dd>
              </>
            )}
            {ev.watchlist_version && (
              <>
                <dt>Watchlist</dt>
                <dd className="mono">{ev.watchlist_version}</dd>
              </>
            )}
          </dl>
          {ev.path && ev.path.length > 0 && (
            <>
              <p className="label">How victim money reached it</p>
              <div className={styles.pathWrap}>
                <div className="table-scroll">
                  <table className={styles.path}>
                    <thead>
                      <tr>
                        <th scope="col">#</th>
                        <th scope="col">From → to</th>
                        <th scope="col" className={styles.num}>Amount</th>
                        <th scope="col">Confidence</th>
                        <th scope="col">Transactions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ev.path.map((h, i) => (
                        <tr key={`${h.from}${h.to}`}>
                          <td className={styles.hopN}>{i + 1}</td>
                          <td className="mono">
                            {shortAddr(h.from)} → {shortAddr(h.to)}
                          </td>
                          <td className={styles.num}>{h.token ? tok(h.amount, h.token) : usdt(h.amount)}</td>
                          <td>
                            {pct(h.confidence)} · {h.method}
                          </td>
                          <td className="mono">
                            {h.tx_hashes.slice(0, 2).map((t) => (
                              <a key={t} href={explorerUrl(chain, "tx", t) ?? undefined} target="_blank" rel="noreferrer" className={styles.tx}>
                                {shortAddr(t)}
                              </a>
                            ))}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
          <ul className={`checks ${styles.fine}`}>
            <li>Reported, not proven</li>
            <li>Hound never holds funds itself; the exchange decides</li>
          </ul>
        </details>
      )}
    </div>
  );
}
