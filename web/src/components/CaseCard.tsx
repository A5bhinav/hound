import type { Case, Trace } from "@/lib/types";
import { explorerUrl, shortAddr, usdt } from "@/lib/format";
import styles from "./CaseCard.module.css";

const REASON: Record<string, string> = {
  exchange: "Reached an exchange",
  holding: "Still sitting here",
  frozen: "Tether froze it",
  dead_end: "Dead end",
  dust: "Dust",
  max_hops: "Hop limit reached",
};

export default function CaseCard({ c, trace }: { c: Case; trace: Trace | null }) {
  const sent = c.sends.reduce((s, x) => s + x.amount, 0);
  return (
    <aside className={styles.card}>
      <p className="eyebrow">Case {c.case_id}</p>
      <h1 className={styles.alias}>{c.victim.alias}</h1>
      <p className={styles.sent}>{usdt(sent)} sent</p>

      <dl className={styles.facts}>
        <dt>Age</dt>
        <dd>{c.victim.age_band}</dd>
        <dt>Sent from</dt>
        <dd>{c.victim.exchange_used ?? "—"}</dd>
        <dt>Scam app</dt>
        <dd>{c.story.scam_app}</dd>
        <dt>Contacted on</dt>
        <dd>{c.story.platform}</dd>
        <dt>First contact</dt>
        <dd>{c.story.first_contact}</dd>
      </dl>
      <p className={styles.summary}>{c.story.summary}</p>

      <p className="eyebrow">Sends</p>
      <ul className={styles.list}>
        {c.sends.map((s, i) => (
          <li key={s.tx_hash || i}>
            <span>{usdt(s.amount)}</span>
            <span className={styles.meta}>
              {s.time.slice(0, 10)} → <span className="mono">{shortAddr(s.to)}</span>
              {s.tx_hash && (
                <>
                  {" · "}
                  <a className="mono" href={explorerUrl(s.chain, "tx", s.tx_hash) ?? undefined} target="_blank" rel="noreferrer">
                    {shortAddr(s.tx_hash)}
                  </a>
                </>
              )}
            </span>
          </li>
        ))}
      </ul>

      {trace && (
        <>
          <p className="eyebrow">Where the money stopped</p>
          <ul className={styles.list}>
            {trace.endpoints.map((p) => (
              <li key={p.address} data-reason={p.reason} data-freezable={p.freezable || undefined}>
                <span>
                  {REASON[p.reason] ?? p.reason}
                  {p.exchange ? `: ${p.exchange}` : ""}
                </span>
                <span className={styles.meta}>
                  {usdt(p.victim_inflow)} of the victim&apos;s money · <span className="mono">{shortAddr(p.address)}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className={styles.method}>
            {trace.method.accounting} · max {trace.method.max_hops} hops · {trace.stats.api_calls} API calls ·{" "}
            {trace.stats.empty_results} empty results
          </p>
        </>
      )}
    </aside>
  );
}
