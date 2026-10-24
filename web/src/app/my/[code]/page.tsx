import Link from "next/link";
import { ApiError, Bar } from "@/components/Chrome";
import VictimCase from "@/components/VictimCase";
import { HoundApiError, getIntakeStatus, usingFixtures, type IntakeStatus } from "@/lib/api";
import styles from "../../victim.module.css";

export const metadata = { title: "Hound: your case" };

/** The victim's own case page, opened with their case code: status until the payment is confirmed, then what we found. */
export default async function MyCase({ params }: PageProps<"/my/[code]">) {
  const code = (await params).code.toUpperCase();
  let s: IntakeStatus | null;
  try {
    s = await getIntakeStatus(code);
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
      <main className="wrap">
        {!s ? (
          <>
            <header className="page-head">
              <div>
                <p className="label">Your case · {code}</p>
                <h1>We can&apos;t find that case code</h1>
              </div>
            </header>
            <div className="grid g2">
              <section className="box" aria-labelledby="try-h">
                <h2 id="try-h" className={styles.boxTitle}>What to try</h2>
                <ul className="checks">
                  <li>Check the six letters and digits</li>
                  <li>
                    Or <Link href="/report">report again</Link>
                  </li>
                  <li>Codes for a report with no payment picture expire after 2 hours</li>
                </ul>
              </section>
              <section className="box box-red" aria-labelledby="never-h">
                <h2 id="never-h" className={styles.boxTitle}>Hound will never</h2>
                <ul className="checks no">
                  <li>Ask you for money, a fee, or a &quot;tax&quot; to release funds</li>
                  <li>Ask for your passwords, seed phrase, recovery phrase or private keys</li>
                </ul>
              </section>
            </div>
          </>
        ) : s.status === "validated" && s.case_id ? (
          <>
            <header className="page-head">
              <div>
                <p className="label">Your case · {code}</p>
                <h1>We found your payment</h1>
              </div>
              <span className="badge badge-ok">Payment confirmed</span>
            </header>
            <VictimCase caseId={s.case_id} code={code} exchangeUsed={s.exchange_used} />
          </>
        ) : (
          <>
            <header className="page-head">
              <div>
                <p className="label">Your case · {code}</p>
                <h1>{s.status === "validating" ? "We are checking your picture" : "We still need a picture of your payment"}</h1>
              </div>
            </header>
            <div className="grid g2">
              <section className={`box ${styles.pending}`}>
                {s.status === "needs_retake" && s.message && <p className={styles.error}>{s.message}</p>}
                {s.status !== "validating" ? (
                  <Link href={`/c/${code}`} className={`btn btn-primary btn-lg ${styles.primary}`}>
                    Send a picture of your payment →
                  </Link>
                ) : (
                  <p className={styles.status} role="status">
                    <span className="badge badge-hold">Checking</span> Reading your picture now
                  </p>
                )}
              </section>
              <section className="box box-red" aria-labelledby="never-h">
                <h2 id="never-h" className={styles.boxTitle}>Hound will never</h2>
                <ul className="checks no">
                  <li>Ask you for money, a fee, or a &quot;tax&quot; to release funds</li>
                  <li>Ask for your passwords, seed phrase, recovery phrase or private keys</li>
                </ul>
              </section>
            </div>
          </>
        )}
      </main>
    </>
  );
}
