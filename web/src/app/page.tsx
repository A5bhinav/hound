import Link from "next/link";
import { ApiError, Bar } from "@/components/Chrome";
import { HoundApiError, listCases, usingFixtures } from "@/lib/api";
import { usdt } from "@/lib/format";
import type { Case } from "@/lib/types";
import styles from "./home.module.css";

const SOURCE: Record<Case["source"], string> = {
  phone: "Phone report",
  screenshot: "Screenshot",
  chainabuse: "Chainabuse report",
  doj_replay: "DOJ replay",
};

export default async function Home() {
  let cases: Case[];
  try {
    cases = await listCases();
  } catch (err) {
    if (!(err instanceof HoundApiError)) throw err;
    return (
      <>
        <Bar sample={usingFixtures} />
        <ApiError message={err.message} />
      </>
    );
  }

  return (
    <>
      <Bar sample={usingFixtures}>Pick a case to trace</Bar>
      <main className={styles.main}>
        <p className="eyebrow">Curated cases</p>
        {cases.length === 0 && <p>No cases yet. Add one under data/cases/ on the backend.</p>}
        <ul className={styles.cases}>
          {cases.map((c) => (
            <li key={c.case_id}>
              <Link href={`/cases/${encodeURIComponent(c.case_id)}`} className={styles.case}>
                <span className={styles.source}>{SOURCE[c.source] ?? c.source}</span>
                <span className={styles.alias}>{c.victim.alias}</span>
                <span className={styles.amount}>{usdt(c.sends.reduce((s, x) => s + x.amount, 0))}</span>
                <span className={styles.story}>
                  {c.story.scam_app} via {c.story.platform} · {c.sends[0]?.chain ?? "—"}
                </span>
                <span className={styles.go}>Trace this case →</span>
              </Link>
            </li>
          ))}
        </ul>
      </main>
    </>
  );
}
