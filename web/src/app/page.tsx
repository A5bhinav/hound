import Link from "next/link";
import { ApiError, Bar } from "@/components/Chrome";
import ResetDemo from "@/components/ResetDemo";
import { HoundApiError, listCases, usingFixtures } from "@/lib/api";
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
      <Bar offline={usingFixtures}>Pick a case to trace</Bar>
      <main className={styles.main}>
        <p className="eyebrow">Curated cases</p>
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
