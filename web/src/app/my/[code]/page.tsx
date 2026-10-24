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
      <main className={styles.main}>
        <p className="eyebrow">Your case · {code}</p>
        {!s ? (
          <>
            <h1 className={styles.h1}>We can&apos;t find that case code</h1>
            <p className={styles.lede}>
              Check the six letters and digits, or <Link href="/report">report again</Link>. Codes for a report with no payment
              picture expire after 2 hours.
            </p>
          </>
        ) : s.status === "validated" && s.case_id ? (
          <>
            <h1 className={styles.h1}>We found your payment</h1>
            <VictimCase caseId={s.case_id} code={code} exchangeUsed={s.exchange_used} />
          </>
        ) : (
          <>
            <h1 className={styles.h1}>{s.status === "validating" ? "We are checking your picture" : "We still need a picture of your payment"}</h1>
            {s.status === "needs_retake" && s.message && <p className={styles.error}>{s.message}</p>}
            {s.status !== "validating" && (
              <Link href={`/c/${code}`} className={styles.primary}>
                Send a picture of your payment →
              </Link>
            )}
          </>
        )}
      </main>
    </>
  );
}
