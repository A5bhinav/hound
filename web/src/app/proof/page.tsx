import Link from "next/link";
import { ApiError, Bar } from "@/components/Chrome";
import { HoundApiError, getProof, usingFixtures, type Backtest, type Scan, type Scoreboard } from "@/lib/api";
import { shortAddr, usdt } from "@/lib/format";
import styles from "./proof.module.css";

export default async function ProofPage() {
  let data: Awaited<ReturnType<typeof getProof>>;
  try {
    data = await getProof();
  } catch (err) {
    if (!(err instanceof HoundApiError)) throw err;
    return (
      <>
        <Bar offline={usingFixtures} />
        <ApiError message={err.message} />
      </>
    );
  }
  return (
    <>
      <Bar offline={usingFixtures}>Proof</Bar>
      <main className={styles.main}>
        <ScoreboardPanel sb={data.scoreboard} />
        <div className={styles.pair}>
          <BacktestPanel bt={data.backtest} />
          <ScanPanel scan={data.scan} />
        </div>
      </main>
    </>
  );
}

function ScoreboardPanel({ sb }: { sb: Scoreboard }) {
  const s = sb.summary;
  // The 4 victim-side inputs (d95, A-1, B-1, C-1) are in the holdout file but were given to the engine.
  const inputs = new Set((sb.inputs ?? []).map((i) => i.address.toLowerCase()));
  const given = sb.holdout.filter((a) => inputs.has(a.toLowerCase()));
  const hidden = sb.holdout.filter((a) => !inputs.has(a.toLowerCase()));
  if (s.status !== "scored") {
    return (
      <section className={styles.panel}>
        <p className="eyebrow">DOJ match · {sb.docket}</p>
        <h1 className={styles.h1}>Not scored yet</h1>
        <p>
          {s.refused_reason ?? "No finished replay trace."} <Link href={`/cases/${sb.case}`}>Run the DOJ replay</Link>, then reload.
        </p>
      </section>
    );
  }
  const finals = sb.targets.filter((t) => t.group === "final");
  const mids = sb.targets.filter((t) => t.group === "intermediate");
  return (
    <section className={styles.panel} aria-labelledby="doj-h">
      <h1 id="doj-h" className={styles.h1}>
        Found all {s.finals_total} wallets the DOJ seized{s.blind ? ", without being told where to look" : ""}
      </h1>
      <p className={styles.lede}>
        {s.intermediates_reached} of {s.intermediates_total} intermediate wallets and {s.finals_reached} of {s.finals_total} final wallets, from the
        victim&apos;s report alone. United States v. 4,340,000 Tether, {sb.docket} ·{" "}
        <a href={sb.source_pdf} target="_blank" rel="noreferrer">complaint</a>
      </p>
      {sb.trace_source === "fixture" && (
        <p className={styles.warn} role="alert">This score comes from a fixture-data trace, not live chain reads.</p>
      )}
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Wallet</th>
            <th scope="col">DOJ</th>
            <th scope="col">Hound</th>
            <th scope="col">Difference</th>
          </tr>
        </thead>
        <tbody>
          {sb.amount.map((a) => (
            <tr key={a.label}>
              <td><b>{a.label}</b> <span className="mono">{shortAddr(a.address)}</span></td>
              <td>{usdt(a.doj_ah_para74_usdt)}</td>
              <td>{a.ours_attributed_usdt == null ? "not reached" : usdt(a.ours_attributed_usdt)}</td>
              <td>
                <span className={styles.band} data-band={a.band}>{signedPct(a.ours_attributed_usdt, a.doj_ah_para74_usdt)}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <details className={styles.more}>
        <summary>How this was scored</summary>
        <p className={styles.note}>
          Amounts are victim A.H.&apos;s money in each final wallet, against DOJ ¶ 74. Green within 5%, amber 5 to 20%, red over 20%.{" "}
          {s.start_disclosure} DOJ also traced 37 other victims and accounts with mixed methods and subpoena data; those totals are
          context only, never scored. Wallets reached: {[...mids, ...finals].filter((t) => t.reached).map((t) => t.label).join(", ")}.
        </p>
        <p className={styles.note}>
          Never given to the engine ({hidden.length}), plus the {given.length} where her sends start and land, which it had to be given:
        </p>
        <ul className={`mono ${styles.addrs}`}>
          {hidden.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}

function BacktestPanel({ bt }: { bt: Backtest }) {
  const ready = bt.n > 0 && bt.detection_lag_median_h != null;
  return (
    <section className={styles.panel} aria-labelledby="bt-h">
      <h2 id="bt-h" className={styles.h2}>
        {ready ? <>When Tether froze a scam wallet in 2025, the money had already sat there a median of <em>{days(bt.detection_lag_median_h!)}</em></> : "Freeze timing: not computed yet"}
      </h2>
      {ready && (
        <p className={styles.lede}>
          {bt.escape_share_median != null && <>By then {Math.round(bt.escape_share_median * 100)}% of the money had already left. </>}
          {bt.p90_h != null && <>The slowest tenth took over {days(bt.p90_h)}.</>}
        </p>
      )}
      <details className={styles.more}>
        <summary>Method</summary>
        <p className={styles.note}>
          {bt.n} frozen addresses measured{bt.population ? ` of ${bt.population}` : ""}
          {bt.n_skipped ? `, ${bt.n_skipped} skipped` : ""}. {bt.method}
        </p>
      </details>
    </section>
  );
}

// AUDIT 24 fields the backend adds per row (hound/proof/scan.py finalize()).
type ScanRow = Scan["cases"][number] & { capped_usdt?: number; cap_basis?: string; row_label?: string; excluded_reasons?: string[] };

function ScanPanel({ scan }: { scan: Scan }) {
  const computed = scan.status !== "not_computed" && scan.addresses > 0;
  // Only rows the backend counted in the headline, at their capped amount, so the list adds up to it.
  const amount = (c: ScanRow) => c.capped_usdt ?? c.balance_usdt;
  const rows = (scan.cases as ScanRow[]).filter((c) => c.freezable_now && !c.is_frozen).sort((a, b) => amount(b) - amount(a));
  const uncapped = rows.some((c) => c.cap_basis?.startsWith("balance"));
  return (
    <section className={styles.panel} aria-labelledby="scan-h">
      <h2 id="scan-h" className={styles.h2}>
        {computed ? <><em>{usdt(Math.round(scan.usdt_unfrozen))}</em> reported and not yet frozen</> : "This weekend's scan: not computed yet"}
      </h2>
      {computed && (
        <p className={styles.lede}>
          In {scan.addresses_unfrozen} of the {scan.addresses} reported addresses checked this weekend. Reported, not proven.
        </p>
      )}
      {computed && rows.length > 0 && (
        <details className={styles.more}>
          <summary>Show the {rows.length} addresses</summary>
          <ul className={styles.scanList}>
            {rows.map((c) => (
              // Live addresses are truncated everywhere public (BRIEF §0).
              <li key={c.address}>
                <span className="mono">{shortAddr(c.address)}</span>
                <span>{usdt(amount(c))}</span>
                {c.category && <span className={styles.cat}>{c.category.toLowerCase().replaceAll("_", " ")}</span>}
              </li>
            ))}
          </ul>
          <p className={styles.note}>
            {scan.already_frozen ? `${scan.already_frozen} already frozen. ` : ""}Each row counts min(balance, claimed losses)
            {uncapped ? " (no claimed-loss figures stored, so rows count at balance)" : ""}; exchange, service and infra wallets and wallets
            with over 2,000 transfers are left out. Sent through Chainabuse / IC3 only, never published.
          </p>
        </details>
      )}
    </section>
  );
}

/** 1076 hours reads as nothing on stage; 45 days does. */
function days(h: number): string {
  const d = h / 24;
  return d >= 2 ? `${Math.round(d)} days` : `${Math.round(h)} h`;
}

/** Ours vs DOJ as a signed percentage with one decimal: +0.9%, +1.0%, +10.8%. "—" when not reached. */
function signedPct(ours: number | null, doj: number): string {
  if (ours == null || !doj) return "—";
  const d = ((ours - doj) / doj) * 100;
  return `${d > 0 ? "+" : ""}${d.toFixed(1)}%`;
}
