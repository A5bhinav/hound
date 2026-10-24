import Link from "next/link";
import { ApiError, Bar } from "@/components/Chrome";
import ResetDemo from "@/components/ResetDemo";
import { HoundApiError, listCases, usingFixtures } from "@/lib/api";
import { tok } from "@/lib/format";
import type { Case, CaseSummary } from "@/lib/types";
import styles from "./home.module.css";

const SOURCE: Record<CaseSummary["source"], string> = {
  phone: "Phone",
  screenshot: "Screenshot",
  chainabuse: "Chainabuse",
  doj_replay: "DOJ replay",
};

/** "Victim A.H. (DOJ replay, US v. …)" reads as "Victim A.H."; the rest is on the case page. */
const title = (c: CaseSummary) => {
  const a = c.victim?.alias ?? c.case_id;
  return a.includes(" (") ? a.slice(0, a.indexOf(" (")) : a;
};

/** What was sent and when: the line that tells two cases apart at a glance. */
function sentLine(c: CaseSummary | Case) {
  const sends = "sends" in c ? c.sends : [];
  if (!sends.length) return c.story?.scam_app ?? null;
  const totals = new Map<string, number>();
  for (const s of sends) totals.set(s.token, (totals.get(s.token) ?? 0) + s.amount);
  const sent = [...totals].map(([t, n]) => tok(Math.round(n * 100) / 100, t)).join(" + ");
  const first = sends.map((s) => s.time).filter(Boolean).sort()[0];
  const when = first ? new Date(first).toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" }) : null;
  return [sends.length > 1 ? `${sent} in ${sends.length} sends` : sent, when].filter(Boolean).join(" · ");
}

export default async function Home() {
  let cases: CaseSummary[];
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
      <Bar offline={usingFixtures} />
      <main className={styles.main}>
        <h1 className={styles.h1}>Follow a scam victim&apos;s money to where it can still be stopped.</h1>
        <p className={styles.sub}>Pick a case. Hound traces it from public chain data and never touches funds.</p>
        {cases.length === 0 && <p>No cases yet.</p>}
        <ul className={styles.cases}>
          {cases.map((c) => (
            <li key={c.case_id}>
              <Link href={`/cases/${encodeURIComponent(c.case_id)}`} className={styles.case}>
                <span className={styles.source} data-source={c.source}>{SOURCE[c.source] ?? c.source}</span>
                <span className={styles.name}>{title(c)}</span>
                <span className={styles.sent}>{sentLine(c)}</span>
                <span className={styles.chev} aria-hidden="true">›</span>
              </Link>
            </li>
          ))}
        </ul>
        {!usingFixtures && <ResetDemo />}
      </main>
    </>
  );
}
