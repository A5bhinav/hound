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
    <section className={`box ${styles.wrap}`} aria-labelledby="others-h">
      <div className="box-h">
        <h2 id="others-h">
          {payers.length === 0 ? "No other wallets paying in" : `${wallets} other ${wallets === 1 ? "wallet" : "wallets"} paying in`}
        </h2>
        {payers.length > 0 && <span className="badge badge-hold">Not confirmed victims</span>}
      </div>
      {payers.length > 0 && (
        <>
          <dl className={`kv ${styles.facts}`}>
            <dt>Payments</dt>
            <dd>{payers.length}</dd>
            <dt>Total in</dt>
            <dd className={styles.num}>{byToken(payers)}</dd>
            <dt>Window</dt>
            <dd>{trace.replay ? `${days} days before the cutoff` : `Last ${days} days`}</dd>
            {exchanges.length > 0 && (
              <>
                <dt>Ask</dt>
                <dd>
                  {list(exchanges)} to warn {exchanges.length === 1 ? "its user" : "their users"}
                </dd>
              </>
            )}
          </dl>
          <details className={styles.more}>
            <summary>Show the payments</summary>
            <ul className={`checks ${styles.caveat}`}>
              <li>Into the scam&apos;s entry wallets</li>
              <li>From wallets other than this victim</li>
              <li>On-chain payments, not confirmed victims</li>
            </ul>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">From</th>
                  <th scope="col" className={styles.r}>Amount</th>
                  <th scope="col">Sent from</th>
                  <th scope="col" className={styles.r}>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {payers.map((p, i) => (
                  <tr key={`${p.address}-${i}`}>
                    <td className="mono">{shortAddr(p.address)}</td>
                    <td className={styles.r}>{amt(p.amount)} {p.token ?? "USDT"}</td>
                    <td>{p.source_exchange ?? "Unknown"}</td>
                    <td className={styles.r}>{pct(p.confidence)}</td>
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
