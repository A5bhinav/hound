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
        <Bar offline={usingFixtures} step="proof" />
        <ApiError message={err.message} />
      </>
    );
  }
  return (
    <>
      <Bar offline={usingFixtures} step="proof" />
      <main className="wrap">
        <ScoreboardPanel sb={data.scoreboard} />
        <div className={`grid g2 ${styles.pair}`}>
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
      <header className="page-head">
        <div>
          <p className="label">DOJ match · {sb.docket}</p>
          <h1>Not scored yet</h1>
          <p className="sub">
            {s.refused_reason ?? "No finished replay trace."} <Link href={`/cases/${sb.case}`}>Run the DOJ replay</Link>, then reload.
          </p>
        </div>
      </header>
    );
  }
  const finals = sb.targets.filter((t) => t.group === "final");
  const mids = sb.targets.filter((t) => t.group === "intermediate");
  return (
    <>
      <header className="page-head">
        <div className={styles.headMain}>
          <p className="label">Proof it works · a real DOJ case{s.blind ? ", run blind" : ""}</p>
          <h1>
            Found all {s.finals_total} wallets the DOJ seized{s.blind ? ", without being told where to look" : ""}
          </h1>
          <p className="sub">From the victim&apos;s report alone.</p>
        </div>
        <dl className={`kv ${styles.caseKv}`}>
          <dt>Case</dt>
          <dd>United States v. 4,340,000 Tether</dd>
          <dt>Docket</dt>
          <dd className="mono">{sb.docket}</dd>
          <dt>Source</dt>
          <dd>
            <a href={sb.source_pdf} target="_blank" rel="noreferrer">complaint</a>
          </dd>
        </dl>
      </header>

      {sb.trace_source === "fixture" && (
        <p className={styles.warn} role="alert">This score comes from a fixture-data trace, not live chain reads.</p>
      )}

      <div className={styles.stats}>
        <div className={styles.stat}>
          <span className="stat-n">
            {s.intermediates_reached} of {s.intermediates_total}
          </span>
          <span className="stat-l">Intermediate wallets the DOJ named, found</span>
        </div>
        <div className={`${styles.stat} ${styles.statRed}`}>
          <span className="stat-n">
            {s.finals_reached} of {s.finals_total}
          </span>
          <span className="stat-l">Final wallets the DOJ seized, found</span>
        </div>
        {sb.amount.map((a) => (
          <div key={a.label} className={styles.stat}>
            <span className={`stat-n ${styles.bandN}`} data-band={a.band}>
              {signedPct(a.ours_attributed_usdt, a.doj_ah_para74_usdt)}
            </span>
            <span className="stat-l">{a.label} amount vs the DOJ&apos;s</span>
          </div>
        ))}
      </div>

      <section className="box" aria-labelledby="doj-h">
        <div className="box-h">
          <h2 id="doj-h">Scoreboard: Hound vs DOJ ¶ 74</h2>
          {s.blind && <span className="badge badge-ok">Blind run</span>}
        </div>
        <div className="table-scroll">
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Wallet</th>
                <th scope="col">Address</th>
                <th scope="col" className={styles.num}>DOJ</th>
                <th scope="col" className={styles.num}>Hound</th>
                <th scope="col" className={styles.num}>Difference</th>
              </tr>
            </thead>
            <tbody>
              {sb.amount.map((a) => (
                <tr key={a.label}>
                  <td><b>{a.label}</b></td>
                  <td className="mono">{shortAddr(a.address)}</td>
                  <td className={styles.num}>{usdt(a.doj_ah_para74_usdt)}</td>
                  <td className={styles.num}>{a.ours_attributed_usdt == null ? "not reached" : usdt(a.ours_attributed_usdt)}</td>
                  <td className={styles.num}>
                    <span className={styles.band} data-band={a.band}>{signedPct(a.ours_attributed_usdt, a.doj_ah_para74_usdt)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <details className={styles.more}>
          <summary>How this was scored</summary>
          <ul className={`checks ${styles.detailList}`}>
            <li>Amounts: victim A.H.&apos;s money in each final wallet, against DOJ ¶ 74</li>
            <li>
              Bands:{" "}
              <span className={styles.band} data-band="green">within 5%</span>{" "}
              <span className={styles.band} data-band="amber">5 to 20%</span>{" "}
              <span className={styles.band} data-band="red">over 20%</span>
            </li>
            {s.start_disclosure && <li>{s.start_disclosure}</li>}
            <li>DOJ also traced 37 other victims and accounts with mixed methods and subpoena data: context only, never scored</li>
            <li>Wallets reached: {[...mids, ...finals].filter((t) => t.reached).map((t) => t.label).join(", ")}</li>
            <li>
              Never given to the engine ({hidden.length}), plus the {given.length} where her sends start and land, which it had to be given
            </li>
          </ul>
          <ul className={`mono ${styles.addrs}`}>
            {hidden.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </details>
      </section>
    </>
  );
}

function BacktestPanel({ bt }: { bt: Backtest }) {
  const ready = bt.n > 0 && bt.detection_lag_median_h != null;
  return (
    <section className="box" aria-labelledby="bt-h">
      <div className="box-h">
        <p className="label">Backtest · Tether freezes in 2025</p>
        {bt.n > 0 && <span className="badge">{bt.n} frozen wallets measured</span>}
      </div>
      <h2 id="bt-h" className={styles.h2}>
        {ready ? "How long scam money sat before Tether froze it" : "Freeze timing: not computed yet"}
      </h2>
      {ready && (
        <div className={`grid ${styles.tiles}`}>
          <div className={styles.stat}>
            <span className="stat-n">{days(bt.detection_lag_median_h!)}</span>
            <span className="stat-l">Median time the money sat there</span>
          </div>
          {bt.escape_share_median != null && (
            <div className={styles.stat}>
              <span className="stat-n">{Math.round(bt.escape_share_median * 100)}%</span>
              <span className="stat-l">Already gone by the freeze (median)</span>
            </div>
          )}
          {bt.p90_h != null && (
            <div className={styles.stat}>
              <span className="stat-n">{days(bt.p90_h)}</span>
              <span className="stat-l">Slowest tenth took longer than this</span>
            </div>
          )}
        </div>
      )}
      <details className={styles.more}>
        <summary>Method</summary>
        <dl className={`kv ${styles.methodKv}`}>
          <dt>Measured</dt>
          <dd>
            {bt.n} frozen addresses{bt.population ? ` of ${bt.population}` : ""}
          </dd>
          {bt.n_skipped ? (
            <>
              <dt>Skipped</dt>
              <dd>{bt.n_skipped}</dd>
            </>
          ) : null}
        </dl>
        <ul className={`checks ${styles.detailList}`}>
          {bt.method
            .split(/\.\s+/)
            .map((l) => l.replace(/\.$/, "").trim())
            .filter(Boolean)
            .map((l) => (
              <li key={l}>{l}</li>
            ))}
        </ul>
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
    <section className="box" aria-labelledby="scan-h">
      <div className="box-h">
        <p className="label">This weekend&apos;s scan</p>
        <span className="badge badge-red">Reported, not proven</span>
      </div>
      <h2 id="scan-h" className={styles.h2}>
        {computed ? "Reported scam money not yet frozen" : "This weekend's scan: not computed yet"}
      </h2>
      {computed && (
        <div className={`grid ${styles.tiles}`}>
          <div className={`${styles.stat} ${styles.statRed}`}>
            <span className="stat-n">{usdt(Math.round(scan.usdt_unfrozen))}</span>
            <span className="stat-l">Reported and not yet frozen</span>
          </div>
          <div className={styles.stat}>
            <span className="stat-n">
              {scan.addresses_unfrozen} of {scan.addresses}
            </span>
            <span className="stat-l">Reported addresses holding it, of those checked this weekend</span>
          </div>
        </div>
      )}
      {computed && rows.length > 0 && (
        <details className={styles.more}>
          <summary>Show the {rows.length} addresses</summary>
          <div className="table-scroll">
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Address</th>
                  <th scope="col" className={styles.num}>Counted</th>
                  <th scope="col">Category</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  // Live addresses are truncated everywhere public (BRIEF §0).
                  <tr key={c.address}>
                    <td className="mono">{shortAddr(c.address)}</td>
                    <td className={styles.num}>{usdt(amount(c))}</td>
                    <td className={styles.cat}>{c.category ? c.category.toLowerCase().replaceAll("_", " ") : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className={`checks ${styles.detailList}`}>
            {scan.already_frozen ? <li>{scan.already_frozen} already frozen</li> : null}
            <li>
              Each row counts min(balance, claimed losses)
              {uncapped ? " (no claimed-loss figures stored, so rows count at balance)" : ""}
            </li>
            <li>Exchange, service and infra wallets and wallets with over 2,000 transfers are left out</li>
            <li>Sent through Chainabuse / IC3 only, never published</li>
          </ul>
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

/** Ours vs DOJ as a signed percentage with one decimal: +0.9%, +1.0%, +10.8%. "not reached" when not reached. */
function signedPct(ours: number | null, doj: number): string {
  if (ours == null || !doj) return "not reached";
  const d = ((ours - doj) / doj) * 100;
  return `${d > 0 ? "+" : ""}${d.toFixed(1)}%`;
}
