import type { OtherPayer, Trace } from "@/lib/types";
import { pct, shortAddr } from "@/lib/format";
import styles from "./OtherPayers.module.css";

const amt = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 2 });

/** BRIEF §4.5: "other wallets paying in", never "victims". One line up front; the payments behind a disclosure. */
export default function OtherPayers({ trace }: { trace: Trace }) {
  const payers = [...trace.other_payers].sort((a, b) => b.amount - a.amount);
  const wallets = new Set(payers.map((p) => p.address.toLowerCase())).size; // rows are payments, not wallets
  const days = payers[0]?.window_days ?? 7;
  const exchanges = [...new Set(payers.map((p) => p.source_exchange).filter(Boolean))] as string[];

  return (
    <section className={styles.wrap} aria-labelledby="others-h">
      <h2 id="others-h" className={styles.head}>
        {payers.length === 0 ? "No other wallets paying in" : `${wallets} other ${wallets === 1 ? "wallet" : "wallets"} paying in`}
      </h2>
      {payers.length > 0 && (
        <>
          <p className={styles.sub}>
            {payers.length} {payers.length === 1 ? "payment" : "payments"} · {byToken(payers)}
            {exchanges.length > 0 && <> · ask {list(exchanges)} to warn {exchanges.length === 1 ? "its user" : "their users"}</>}
          </p>
          <details className={styles.more}>
            <summary>Show the payments</summary>
            <p className={styles.caveat}>
              {trace.replay ? `${days} days before the cutoff` : `Last ${days} days`}, into the scam&apos;s entry wallets, from wallets
              other than this victim. On-chain payments, not confirmed victims.
            </p>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">From</th>
                  <th scope="col">Amount</th>
                  <th scope="col">Sent from</th>
                  <th scope="col">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {payers.map((p, i) => (
                  <tr key={`${p.address}-${i}`}>
                    <td className="mono">{shortAddr(p.address)}</td>
                    <td>{amt(p.amount)} {p.token ?? "USDT"}</td>
                    <td>{p.source_exchange ?? "Unknown"}</td>
                    <td>{pct(p.confidence)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </section>
  );
}

const list = (xs: string[]) => (xs.length < 3 ? xs.join(" and ") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);

/** Sum payments per token ("19,896.3 USDT + 33.21 ETH"): different tokens are never added together. */
function byToken(ps: OtherPayer[]): string {
  const sums = new Map<string, number>();
  for (const p of ps) sums.set(p.token ?? "USDT", (sums.get(p.token ?? "USDT") ?? 0) + p.amount);
  return [...sums].map(([tok, n]) => `${amt(n)} ${tok}`).join(" + ");
}
