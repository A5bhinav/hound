import type { OtherPayer, Trace } from "@/lib/types";
import { pct, shortAddr } from "@/lib/format";
import styles from "./OtherPayers.module.css";

const amt = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 2 });

/** BRIEF §4.5: "other wallets paying in", never "victims". The exchange each payer sent from is who warns them. */
export default function OtherPayers({ trace }: { trace: Trace }) {
  const payers = [...trace.other_payers].sort((a, b) => b.amount - a.amount);
  const wallets = new Set(payers.map((p) => p.address.toLowerCase())).size;  // rows are payments, not wallets
  const days = payers[0]?.window_days ?? 7;
  const byExchange = new Map<string, OtherPayer[]>();
  for (const p of payers) {
    const k = p.source_exchange ?? "Unknown source";
    byExchange.set(k, [...(byExchange.get(k) ?? []), p]);
  }

  return (
    <section className={styles.wrap} aria-labelledby="others-h">
      <p className="eyebrow">The same scam, other senders</p>
      <h2 id="others-h" className={styles.head}>
        {payers.length === 0
          ? "No other wallets found paying in"
          : `${payers.length} ${payers.length === 1 ? "payment" : "payments"} from ${wallets} other ${wallets === 1 ? "wallet" : "wallets"} into this scam`}
      </h2>
      <p className={styles.sub}>
        {trace.replay ? `In the ${days} days before the cutoff` : `In the last ${days} days`}, payments into the scam&apos;s entry
        wallets from senders other than this victim. On-chain counts, not confirmed victims.
        {trace.replay && " The DOJ complaint (context only) lists 38 victims and victim accounts."}
      </p>

      {payers.length > 0 && (
        <>
          <ul className={styles.exchanges}>
            {[...byExchange].map(([ex, list]) => {
              // Rows are payments; a sender is a distinct wallet (review F4).
              const n = new Set(list.map((p) => p.address.toLowerCase())).size;
              return (
              <li key={ex}>
                <strong>{ex}</strong>
                <span>
                  {n} {n === 1 ? "sender" : "senders"} · {list.length} {list.length === 1 ? "payment" : "payments"} ·{" "}
                  {byToken(list)} sent
                </span>
                {ex !== "Unknown source" && <span className={styles.ask}>Ask {ex} to warn their user before the next send.</span>}
              </li>
              );
            })}
          </ul>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Sending wallet</th>
                  <th scope="col">Amount</th>
                  <th scope="col">Sent from</th>
                  <th scope="col">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {payers.map((p, i) => (
                  <tr key={`${p.address}-${i}`}>
                    <td className="mono">{shortAddr(p.address)}</td>
                    <td className="mono">{amt(p.amount)} {p.token ?? "USDT"}</td>
                    <td>{p.source_exchange ?? "Unknown"}</td>
                    <td>{pct(p.confidence)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

/** Sum a group's payments per token ("19,929.51 USDT + 6.03 ETH"): different tokens are never added together. */
function byToken(list: OtherPayer[]): string {
  const sums = new Map<string, number>();
  for (const p of list) sums.set(p.token ?? "USDT", (sums.get(p.token ?? "USDT") ?? 0) + p.amount);
  return [...sums].map(([tok, n]) => `${amt(n)} ${tok}`).join(" + ");
}
