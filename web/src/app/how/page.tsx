import Link from "next/link";
import { ApiError, Bar, DEMO_CASE } from "@/components/Chrome";
import ResetDemo from "@/components/ResetDemo";
import { HoundApiError, listCases, usingFixtures } from "@/lib/api";
import { tok } from "@/lib/format";
import type { Case, CaseSummary } from "@/lib/types";
import styles from "./how.module.css";

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

const HOW = [
  { title: "Report", href: "/intake", text: "The victim calls the hotline, gets a text link and sends a screenshot of the payment." },
  { title: "Follow the money", href: `/cases/${DEMO_CASE}`, text: "Every wallet the money passed through, and where it sits now." },
  { title: "Stop the next victim", href: "/exchange", text: "Exchanges hold withdrawals to wallets on the warning list." },
  { title: "Police report", href: `/cases/${DEMO_CASE}/packet`, text: "One page a detective can act on, with who to contact." },
];

export const metadata = { title: "How Hound works" };

export default async function How() {
  let cases: CaseSummary[];
  try {
    cases = await listCases();
  } catch (err) {
    if (!(err instanceof HoundApiError)) throw err;
    return (
      <>
        <Bar offline={usingFixtures} step="tour" />
        <ApiError message={err.message} />
      </>
    );
  }

  return (
    <>
      <Bar offline={usingFixtures} step="tour" />
      <main className={styles.main}>
        <p className="eyebrow">How Hound works · for judges, exchanges and police</p>
        <h1 className={styles.h1}>Hound follows stolen crypto and stops it moving again.</h1>
        <p className={styles.sub}>
          A scam victim calls. Hound traces their money to where it sits, warns exchanges before the next victim pays the
          same wallets, and hands police a one-page report.
        </p>
        <Link href="/intake" className={styles.start}>
          Walk through it: 1 Report →
        </Link>

        <h2 className={styles.h2}>How it works</h2>
        <ol className={styles.how}>
          {HOW.map((h, i) => (
            <li key={h.title}>
              <Link href={h.href} className={styles.howCard}>
                <span className={styles.howN}>{i + 1}</span>
                <span className={styles.howTitle}>{h.title}</span>
                <span className={styles.howText}>{h.text}</span>
              </Link>
            </li>
          ))}
        </ol>
        <p className={styles.proof}>
          <Link href="/proof">Proof it works:</Link> run blind on a real 2024 DOJ case, Hound found all 3 wallets the DOJ seized.
        </p>

        <h2 className={styles.h2}>Cases</h2>
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
