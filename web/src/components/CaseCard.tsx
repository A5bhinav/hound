import type { Case, CaseSummary, EndpointReason, Trace } from "@/lib/types";
import { explorerUrl, shortAddr, usdt } from "@/lib/format";
import styles from "./CaseCard.module.css";

const REASON: Record<EndpointReason, string> = {
  exchange: "Reached an exchange",
  holding: "Sitting in a wallet",
  frozen: "Tether froze it",
  dead_end: "Dead end",
  dust: "Dust",
  max_hops: "Hop limit reached",
  capped: "Branch limit reached",
  high_volume: "High-volume wallet, not expanded",
  budget: "API budget reached",
  time_cap: "Time limit reached",
  swap_unresolved: "Swap not resolved",
  tether_destroyed: "Tether destroyed the funds",
};

const FACTS: [string, (c: CaseSummary) => string | null | undefined][] = [
  ["Age", (c) => c.victim?.age_band],
  ["Sent from", (c) => c.victim?.exchange_used],
  ["Scam app", (c) => c.story?.scam_app],
  ["Contacted on", (c) => c.story?.platform],
  ["First contact", (c) => c.story?.first_contact],
];

export default function CaseCard({ c, trace }: { c: CaseSummary | Case; trace: Trace }) {
  // GET /cases has no sends; the trace's seeds are the same transfers.
  const sends = "sends" in c ? c.sends : null;
  const total = sends ? sends.reduce((s, x) => s + x.amount, 0) : trace.seeds.reduce((s, x) => s + x.amount, 0);
  const chain = trace.nodes[0]?.chain ?? "ethereum";
  const facts = FACTS.map(([k, get]) => [k, get(c)] as const).filter(([, v]) => v && v !== "unknown");
  const asOf = "as_of" in c ? c.as_of : null;

  return (
    <aside className={styles.card}>
      <p className="eyebrow">
        {trace.replay ? "Replay · historical case" : "Case"} · {c.case_id}
      </p>
      <h1 className={styles.alias} data-long={(c.victim?.alias ?? c.case_id).length > 28 || undefined}>
        {c.victim?.alias ?? c.case_id}
      </h1>
      <p className={styles.sent}>
        {usdt(total)} in {(sends ?? trace.seeds).length} sends
      </p>
      {trace.replay && asOf && <p className={styles.replay}>Traced as of {asOf.slice(0, 10)}, the date the victim reported.</p>}

      {facts.length > 0 && (
        <dl className={styles.facts}>
          {facts.map(([k, v]) => (
            <div key={k} className={styles.fact}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {c.story?.summary && <p className={styles.summary}>{c.story.summary}</p>}

      <p className="eyebrow">Sends</p>
      <ul className={`${styles.list} ${styles.sends}`}>
        {(sends ?? trace.seeds).map((s) => (
          <li key={s.tx_hash}>
            <span>{usdt(s.amount)}</span>
            <span className={styles.meta}>
              {"time" in s && <>{s.time.slice(0, 10)} · </>}
              <a className="mono" href={explorerUrl(chain, "tx", s.tx_hash) ?? undefined} target="_blank" rel="noreferrer">
                {shortAddr(s.tx_hash)}
              </a>
            </span>
          </li>
        ))}
      </ul>

      <p className="eyebrow">Where the money stopped</p>
      <ul className={styles.list}>
        {trace.endpoints.map((p) => (
          <li key={p.address} data-reason={p.reason} data-freezable={p.freezable || undefined}>
            <span>
              {REASON[p.reason] ?? p.reason}
              {p.exchange ? `: ${p.exchange}` : ""}
            </span>
            <span className={styles.meta}>
              {usdt(p.victim_inflow)} of victim money in
              {p.victim_remaining != null && <>, {usdt(p.victim_remaining)} still there{trace.replay ? " at cutoff" : ""}</>}
              {" · "}
              <span className="mono">{shortAddr(p.address)}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className={styles.method}>
        {trace.method.accounting} · max {trace.method.max_hops} hops
        {trace.method.as_of_block ? ` · cutoff block ${trace.method.as_of_block}` : ""} · {trace.stats.api_calls} API calls ·{" "}
        {trace.stats.empty_results} empty results
      </p>
    </aside>
  );
}
