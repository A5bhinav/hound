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
      <p className="eyebrow">
        DOJ match · United States v. 4,340,000 Tether · {sb.docket} ·{" "}
        <a href={sb.source_pdf} target="_blank" rel="noreferrer">
          complaint PDF
        </a>
      </p>
      <h1 id="doj-h" className={styles.h1}>
        Reached the same {s.finals_total} wallets DOJ seized{s.blind ? ", blind" : ""}
      </h1>
      {sb.trace_source === "fixture" && (
        <p className={styles.warn} role="alert">
          This score comes from a fixture-data trace, not live chain reads.
        </p>
      )}

      <div className={styles.big}>
        <Stat n={`${s.intermediates_reached}/${s.intermediates_total}`} label="DOJ intermediate wallets reached" />
        <Stat n={`${s.finals_reached}/${s.finals_total}`} label="final wallets reached (A-7, A-8, A-9)" />
      </div>

      <ul className={styles.chips} aria-label="Wallets DOJ named">
        {[...mids, ...finals].map((t) => (
          <li key={t.label} data-reached={t.reached || undefined} title={t.address}>
            {t.label}
          </li>
        ))}
      </ul>

      <h2 className={styles.h2}>Victim A.H.&apos;s money in each final wallet: ours vs DOJ (¶ 74)</h2>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Wallet</th>
              <th scope="col">DOJ ¶ 74</th>
              <th scope="col">Hound</th>
              <th scope="col">Difference</th>
            </tr>
          </thead>
          <tbody>
            {sb.amount.map((a) => (
              <tr key={a.label}>
                <td>
                  {a.label} <span className="mono">{shortAddr(a.address)}</span>
                </td>
                <td className="mono">{usdt(a.doj_ah_para74_usdt)}</td>
                <td className="mono">{a.ours_attributed_usdt == null ? "not reached" : usdt(a.ours_attributed_usdt)}</td>
                <td>
                  <span className={styles.band} data-band={a.band}>
                    {a.pct_error == null ? "—" : `${a.pct_error}%`}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={styles.note}>
        Green ≤ 5%, amber 5–20%, red over 20%. {s.start_disclosure} DOJ also traced 37 other victims and accounts with mixed methods and
        subpoena data; those totals are context only, never scored.
      </p>
      <details className={styles.holdout}>
        <summary>
          Holdout: the {hidden.length} DOJ addresses the engine was never given (plus the {given.length} where the
          victim&apos;s sends start and land, which it had to be given)
        </summary>
        <ul className="mono">
          {hidden.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}

function BacktestPanel({ bt }: { bt: Backtest }) {
  return (
    <section className={styles.panel} aria-labelledby="bt-h">
      <p className="eyebrow">Freeze backtest</p>
      <h2 id="bt-h" className={styles.h2}>
        How long scam money sat before Tether froze it
      </h2>
      {bt.n === 0 || bt.detection_lag_median_h == null ? (
        <p className={styles.empty}>Not computed yet. {bt.method}</p>
      ) : (
        <>
          <div className={styles.big}>
            <Stat n={days(bt.detection_lag_median_h)} label="median, first stolen dollar in to Tether's freeze" />
            {bt.p90_h != null && <Stat n={days(bt.p90_h)} label="90th percentile" />}
            {bt.escape_share_median != null && (
              <Stat n={`${Math.round(bt.escape_share_median * 100)}%`} label="median share moved out before the freeze" />
            )}
          </div>
          <p className={styles.note}>
            {bt.n} frozen addresses measured{bt.population ? ` of ${bt.population}` : ""}
            {bt.n_skipped ? `, ${bt.n_skipped} skipped` : ""}. {bt.method}
          </p>
        </>
      )}
    </section>
  );
}

// AUDIT 24 fields the backend adds per row (hound/proof/scan.py finalize()).
type ScanRow = Scan["cases"][number] & { capped_usdt?: number; cap_basis?: string; row_label?: string; excluded_reasons?: string[] };
const SCAN_ROWS_SHOWN = 8;

function ScanPanel({ scan }: { scan: Scan }) {
  const computed = scan.status !== "not_computed" && scan.addresses > 0;
  // Only rows the backend counted in the headline, at their capped amount, so the list adds up to it.
  const amount = (c: ScanRow) => c.capped_usdt ?? c.balance_usdt;
  // Largest first, whatever order the summary file was written in (review F1).
  const rows = (scan.cases as ScanRow[]).filter((c) => c.freezable_now && !c.is_frozen).sort((a, b) => amount(b) - amount(a));
  const shown = rows.slice(0, SCAN_ROWS_SHOWN);
  const rest = rows.slice(SCAN_ROWS_SHOWN);
  const uncapped = rows.some((c) => c.cap_basis?.startsWith("balance"));
  return (
    <section className={styles.panel} aria-labelledby="scan-h">
      <p className="eyebrow">This weekend · {scan.label}</p>
      <h2 id="scan-h" className={styles.h2}>
        Reported scam money not yet frozen
      </h2>
      {!computed ? (
        <p className={styles.empty}>Not computed yet. {scan.method}</p>
      ) : (
        <>
          <div className={styles.big}>
            <Stat n={usdt(scan.usdt_unfrozen)} label={`in ${scan.addresses_unfrozen} addresses not yet frozen`} />
          </div>
          <ul className={styles.scanList}>
            {shown.map((c) => (
              // Live addresses are truncated everywhere public (BRIEF §0).
              <li key={c.address}>
                <span className="mono">{shortAddr(c.address)}</span>
                <span>{usdt(amount(c))}</span>
                {c.category && <span className={styles.cat}>{c.category}</span>}
                <span className={styles.cat}>{c.row_label ?? scan.label}</span>
              </li>
            ))}
            {rest.length > 0 && (
              <li key="rest">
                <span>+{rest.length} more</span>
                <span>{usdt(rest.reduce((s, c) => s + amount(c), 0))}</span>
              </li>
            )}
          </ul>
          <p className={styles.note}>
            {scan.addresses} reported addresses scanned{scan.scanned_at ? ` on ${scan.scanned_at.slice(0, 10)}` : ""}
            {scan.already_frozen ? `, ${scan.already_frozen} already frozen` : ""}. Each row counts min(balance, claimed losses)
            {uncapped ? " (this run stored no claimed-loss figures, so rows count at balance)" : ""}; exchange, service and infra wallets and wallets with over 2,000 transfers are left out. Sent through Chainabuse / IC3 only, never published.
          </p>
        </>
      )}
    </section>
  );
}

function Stat({ n, label }: { n: string; label: string }) {
  return (
    <div className={styles.stat}>
      <span className={styles.statN}>{n}</span>
      <span className={styles.statL}>{label}</span>
    </div>
  );
}

/** 1076 hours reads as nothing on stage; 45 days does. */
function days(h: number): string {
  const d = h / 24;
  return d >= 2 ? `${Math.round(d)} days` : `${Math.round(h)} h`;
}
