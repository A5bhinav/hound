import Link from "next/link";
import { ApiError, Bar } from "@/components/Chrome";
import ResetDemo from "@/components/ResetDemo";
import { HoundApiError, getProof, listCases, usingFixtures } from "@/lib/api";
import type { CaseSummary } from "@/lib/types";
import styles from "./home.module.css";

const SOURCE: Record<CaseSummary["source"], string> = {
  phone: "Phone report",
  screenshot: "Screenshot",
  chainabuse: "Chainabuse report",
  doj_replay: "DOJ replay",
};

function storyLine(c: CaseSummary) {
  const { scam_app, platform } = c.story ?? {};
  if (scam_app && platform) return `${scam_app} via ${platform}`;
  // One word like "text message" says less than the summary; prefer the summary when there is one (review F16).
  return c.story?.summary ?? scam_app ?? platform ?? null;
}

/** Three true numbers from the backend for the opening line; the page still renders without them. */
async function headline() {
  try {
    const { scoreboard, backtest, scan } = await getProof();
    const s = scoreboard.summary;
    const reach = s.status === "scored" ? `${s.intermediates_reached}/${s.intermediates_total} + ${s.finals_reached}/${s.finals_total}` : null;
    const days = backtest.detection_lag_median_h ? Math.round(backtest.detection_lag_median_h / 24) : null;
    return { reach, days, scanned: scan.addresses || null };
  } catch {
    return null;
  }
}

export default async function Home() {
  let cases: CaseSummary[];
  const stats = usingFixtures ? null : await headline();
  try {
    cases = await listCases();
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
      <Bar offline={usingFixtures}>Pick a case to trace</Bar>
      <main className={styles.main}>
        <section className={styles.hero} aria-label="What Hound does">
          <h1 className={styles.h1}>One victim&apos;s report. The money, followed to where it can still be stopped.</h1>
          <p className={styles.sub}>Public chain data only. Never touches money, never asks for keys. Findings go to the exchange, Tether and IC3, labelled reported, not proven.</p>
          {stats && (
            <ul className={styles.tiles}>
              {stats.reach && (
                <li><b>{stats.reach}</b><span>DOJ wallets reached blind: intermediates it was never given, plus all three seized</span></li>
              )}
              {stats.days && (
                <li><b>{stats.days} days</b><span>median wait before Tether froze a scam wallet in 2025, measured on chain</span></li>
              )}
              {stats.scanned && (
                <li><b>{stats.scanned.toLocaleString("en-US")}</b><span>reported scam addresses checked on chain this weekend</span></li>
              )}
            </ul>
          )}
        </section>
        <h2 className={styles.h2}>Pick a case to trace</h2>
        {cases.length === 0 && <p>No cases yet. Add one under data/cases/ on the backend.</p>}
        <ul className={styles.cases}>
          {cases.map((c) => (
            <li key={c.case_id}>
              <Link href={`/cases/${encodeURIComponent(c.case_id)}`} className={styles.case}>
                <span className={styles.source}>{SOURCE[c.source] ?? c.source}</span>
                <span className={styles.alias}>{c.victim?.alias ?? c.case_id}</span>
                {storyLine(c) && <span className={styles.story}>{storyLine(c)}</span>}
                <span className={styles.go}>Trace this case →</span>
              </Link>
            </li>
          ))}
        </ul>
        {!usingFixtures && <ResetDemo />}
      </main>
    </>
  );
}
