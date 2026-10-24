"use client";

import { useState } from "react";
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
  { label: "A scam wallet from the DOJ replay", chain: "ethereum", address: "0xa1770ead287dc8e91631a7a323390d5b744f0021" },
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
  const amountN = Number(amount.trim());
  const amountOk = amount.trim() !== "" && Number.isFinite(amountN) && amountN > 0;

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
      <div className={styles.exchange}>
        <header className={styles.exHead}>
          <span className={styles.exName}>Demo Exchange</span>
          <span className={styles.exTag}>Mock withdrawal screen · Hound check API</span>
        </header>

        <form className={styles.form} onSubmit={submit}>
          <h1 className={styles.title}>Withdraw USDT</h1>
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
            {!amountOk && <span role="alert">Enter an amount above 0.</span>}
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

        {phase.k === "error" && (
          <div className={styles.result} data-decision="error" role="alert">
            <p className={styles.verdict}>Couldn&apos;t check this address</p>
            <p>{phase.message}</p>
          </div>
        )}
        {phase.k === "result" && <Result r={phase.r} address={phase.address} chain={phase.chain} amount={phase.amount} />}
      </div>
    </div>
  );
}

function Result({ r, address, chain, amount }: { r: CheckResult; address: string; chain: Chain; amount: number }) {
  const ev = r.evidence;
  return (
    <div className={styles.result} data-decision={r.decision} role={r.decision === "allow" ? "status" : "alert"}>
      <p className={styles.verdict}>{HEADLINE[r.decision]}</p>
      <p className={styles.lede}>
        {r.decision === "hold" && `Your ${usdt(amount)} has not left your account. This address is part of a traced scam cluster.`}
        {r.decision === "warn" && "This address is linked to reported scam activity. Confirm you know who you're paying before you send."}
        {r.decision === "allow" && "No Hound warning for this address. That doesn't prove it's safe."}
      </p>
      <ul className={styles.reasons}>
        {r.reasons.map((x) => (
          <li key={x}>{x}</li>
        ))}
      </ul>

      {r.decision !== "allow" && (
        <details className={styles.evidence} open={r.decision === "hold"}>
          <summary>Evidence for the exchange&apos;s fraud team</summary>
          <dl>
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
                  {ev.frozen.frozen_at?.slice(0, 10) ?? "date unknown"}
                  {ev.frozen.freeze_tx && (
                    <>
                      {" · "}
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
              <p className="eyebrow">How victim money reached it</p>
              <ol className={styles.path}>
                {ev.path.map((h) => (
                  <li key={`${h.from}${h.to}`}>
                    <span className="mono">
                      {shortAddr(h.from)} → {shortAddr(h.to)}
                    </span>
                    <span>
                      {h.token ? tok(h.amount, h.token) : usdt(h.amount)} · {pct(h.confidence)} · {h.method}
                    </span>
                    <span className="mono">
                      {h.tx_hashes.slice(0, 2).map((t) => (
                        <a key={t} href={explorerUrl(chain, "tx", t) ?? undefined} target="_blank" rel="noreferrer">
                          {shortAddr(t)}{" "}
                        </a>
                      ))}
                    </span>
                  </li>
                ))}
              </ol>
            </>
          )}
          <p className={styles.fine}>Reported, not proven. Hound never holds funds itself; the exchange decides.</p>
        </details>
      )}
    </div>
  );
}
