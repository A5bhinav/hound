import type { Case, CaseSummary, Endpoint, EndpointReason, Trace } from "@/lib/types";
import { explorerUrl, shortAddr, tok, usdt } from "@/lib/format";

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

/** trace is null while it is still running. */
export default function CaseCard({
  c,
  trace,
  freezesShown = true,
}: {
  c: CaseSummary | Case;
  trace: Trace | null;
  /** false while a replay is still hiding freezes (the graph reveals them after the last hop). */
  freezesShown?: boolean;
}) {
  // GET /cases has no sends; the trace's seeds are the same transfers.
  const sendList = "sends" in c ? c.sends : (trace?.seeds ?? []);
  // Sends can be ETH (replay) or USDT; never label one token as another. Sum per token.
  const totals = new Map<string, number>();
  for (const s of sendList) totals.set(s.token, (totals.get(s.token) ?? 0) + s.amount);
  const totalText = [...totals].map(([token, n]) => tok(n, token)).join(" + ");
  const chain = trace?.nodes[0]?.chain ?? ("sends" in c ? c.sends[0]?.chain : undefined) ?? "ethereum";
  const facts = FACTS.map(([k, get]) => [k, get(c)] as const).filter(([, v]) => v && v !== "unknown");
  const asOf = "as_of" in c ? c.as_of : null;
  const replay = trace?.replay ?? c.source === "doj_replay";

  return (
    <aside className={styles.card}>
      <p className="eyebrow">
        {replay ? "Replay · historical case" : "Case"} · {c.case_id}
      </p>
      <h1 className={styles.alias} data-long={(c.victim?.alias ?? c.case_id).length > 28 || undefined}>
        {c.victim?.alias ?? c.case_id}
      </h1>
      {sendList.length > 0 && (
        <p className={styles.sent}>
          {totalText} in {sendList.length} {sendList.length === 1 ? "send" : "sends"}
        </p>
      )}
      {replay && (trace?.method.as_of_block || asOf) && (
        // The cutoff is a block just before Tether's last freeze; the report date is only the story date (review web-integration-4).
        <p className={styles.replay}>
          {trace?.method.as_of_block ? `Chain data up to block ${trace.method.as_of_block}, just before Tether's last freeze.` : ""}
          {asOf ? ` The victim reported on ${asOf.slice(0, 10)}.` : ""}
        </p>
      )}

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

      {sendList.length > 0 && <p className="eyebrow">Sends</p>}
      <ul className={`${styles.list} ${styles.sends}`}>
        {sendList.map((s) => (
          <li key={s.tx_hash}>
            <span>
              {tok(s.amount, s.token)}
            </span>
            <span className={styles.meta}>
              {"time" in s && <>{s.time.slice(0, 10)} · </>}
              <a className="mono" href={explorerUrl(chain, "tx", s.tx_hash) ?? undefined} target="_blank" rel="noreferrer">
                {shortAddr(s.tx_hash)}
              </a>
            </span>
          </li>
        ))}
      </ul>

      {trace && <Endpoints trace={trace} freezesShown={freezesShown} />}
    </aside>
  );
}

function stopLabel(p: Endpoint, trace: Trace, frozenAt: string | null) {
  if (frozenAt) return `Tether froze it on ${frozenAt.slice(0, 10)}`;
  // The trail went on past this address; only a small residual stayed (review F12).
  // Not for swap_unresolved: there the signal is that the swap could not be followed.
  const residual = p.reason === "dust" || p.reason === "holding" || (p.victim_remaining ?? 0) > 0;
  if (p.reason !== "swap_unresolved" && residual && trace.edges.some((e) => e.from === p.address))
    return "Small residual left behind, the money moved on";
  if (p.reason === "swap_unresolved") return "Swap not resolved here, part of the money could not be followed";
  if (p.reason === "holding" && trace.replay) return "Was sitting here at cutoff";
  return `${REASON[p.reason] ?? p.reason}${p.exchange ? `: ${p.exchange}` : ""}`;
}

/** Exchanges: money that reached it. Everything else: money still there, so stops never double-count (review contracts-9). */
function stopAmount(p: Endpoint, replay: boolean | undefined) {
  if (p.reason === "exchange" || p.victim_remaining == null) return `${usdt(p.victim_inflow)} of victim money reached it`;
  const passed = p.victim_inflow - p.victim_remaining;
  return `${usdt(p.victim_remaining)} of victim money still here${replay ? " at cutoff" : ""}${
    passed >= 0.01 ? ` (${usdt(passed)} passed through)` : ""
  }`;
}

function Endpoints({ trace, freezesShown }: { trace: Trace; freezesShown: boolean }) {
  const frozenAt = (addr: string) => {
    const n = trace.nodes.find((x) => x.address === addr);
    return freezesShown && n?.frozen?.is_frozen ? (n.frozen.frozen_at ?? "") : null;
  };
  return (
    <>
      <p className="eyebrow">Where the money stopped</p>
      <ul className={styles.list}>
        {trace.endpoints.filter((p) => p.victim_inflow > 0 || (p.victim_remaining ?? 0) > 0).map((p) => {
          const fz = frozenAt(p.address);
          return (
            <li key={p.address} data-reason={fz !== null ? "frozen" : p.reason} data-freezable={p.freezable || undefined}>
              <span>{stopLabel(p, trace, fz || null)}</span>
              <span className={styles.meta}>
                {stopAmount(p, trace.replay)}
                {" · "}
                <span className="mono">{shortAddr(p.address)}</span>
              </span>
            </li>
          );
        })}
      </ul>
      <p className={styles.method}>
        {trace.method.accounting} · max {trace.method.max_hops} hops
        {trace.method.as_of_block ? ` · cutoff block ${trace.method.as_of_block}` : ""} · {trace.stats.api_calls} API calls ·{" "}
        {trace.stats.empty_results} empty results
      </p>
    </>
  );
}
