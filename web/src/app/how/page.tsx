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
  { title: "Report", href: "/intake", points: ["Victim calls the hotline or reports online", "Hears the website and a case code", "Uploads a payment screenshot"] },
  { title: "Follow the money", href: `/cases/${DEMO_CASE}`, points: ["Every wallet the money passed", "Where it sits now", "Which wallets Tether froze"] },
  { title: "Stop the next victim", href: "/exchange", points: ["Traced wallets go on a warning list", "Exchanges check before a withdrawal", "Hold, warn or allow"] },
  { title: "Police report", href: `/cases/${DEMO_CASE}/packet`, points: ["One page for a detective", "Every transfer, cited", "Who to contact"] },
];

/** The DOJ replay scoreboard (PITCH.md, engine test test_reaches_doj_seized_wallets_blind). */
const PROOF = [
  { n: "8 of 8", l: "Wallets in between the DOJ named, found blind" },
  { n: "3 of 3", l: "Wallets the DOJ seized, found blind" },
  { n: "~1%", l: "A-7 and A-8 amounts vs the DOJ's own numbers" },
  { n: "16–20 days", l: "Before Tether froze them, after the victim reported" },
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
      <main className="wrap">
        <header className="page-head">
          <div>
            <p className="eyebrow">How Hound works · for judges, exchanges and police</p>
            <h1>
              Hound follows stolen crypto
              <br />
              <span className="quiet">and stops it moving again.</span>
            </h1>
            <p className="sub">Victim report in. Traced wallets, exchange holds and a police report out.</p>
            <div className="ctas">
              <Link href="/intake" className="btn btn-primary btn-lg">
                Walk through it: 1 Report →
              </Link>
              <Link href="/proof" className="btn btn-lg">
                Proof it works
              </Link>
            </div>
          </div>
        </header>

        <ol className={`grid g4 ${styles.how}`}>
          {HOW.map((h, i) => (
            <li key={h.title}>
              <Link href={h.href} className={`box ${styles.howCard}`}>
                <span className={styles.howN}>{i + 1}</span>
                <h2 className={styles.howTitle}>{h.title}</h2>
                <ul className="checks">
                  {h.points.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              </Link>
            </li>
          ))}
        </ol>

        <section className={`box ${styles.proofBox}`} aria-labelledby="proof-h">
          <div className="box-h">
            <h2 id="proof-h">Proof: a real 2024 DOJ case, run blind</h2>
            <Link href="/proof" className="btn">Proof it works →</Link>
          </div>
          <div className="grid g4">
            {PROOF.map((p) => (
              <div key={p.n} className={styles.stat}>
                <span className="stat-n">{p.n}</span>
                <span className="stat-l">{p.l}</span>
              </div>
            ))}
          </div>
        </section>

        <section className={`box ${styles.casesBox}`} aria-labelledby="cases-h">
          <h2 id="cases-h" className={styles.h2}>Cases</h2>
          {cases.length === 0 && <p className="small">No cases yet.</p>}
          <ul className={styles.cases}>
            {cases.map((c) => (
              <li key={c.case_id}>
                <Link href={`/cases/${encodeURIComponent(c.case_id)}`} className={styles.case}>
                  <span className={`badge ${c.source === "doj_replay" ? "badge-ice" : ""} ${styles.source}`}>{SOURCE[c.source] ?? c.source}</span>
                  <span className={styles.name}>{title(c)}</span>
                  <span className={styles.sent}>{sentLine(c)}</span>
                  <span className={styles.chev} aria-hidden="true">›</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
        {!usingFixtures && <ResetDemo />}
      </main>
    </>
  );
}
