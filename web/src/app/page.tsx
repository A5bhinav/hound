import Link from "next/link";
import { Bar } from "@/components/Chrome";
import { getPublicInfo, usingFixtures } from "@/lib/api";
import styles from "./victim.module.css";

export const metadata = { title: "Hound: help after a crypto scam" };

/** +16812755467 reads as (681) 275-5467. */
function formatPhone(p: string) {
  const m = p.replace(/\D/g, "").match(/^1?(\d{3})(\d{3})(\d{4})$/);
  return m ? `(${m[1]}) ${m[2]}-${m[3]}` : p;
}

/** The victim's front door: two ways to report, a way back to an open case, and what Hound will never do. */
export default async function Home() {
  const { phone } = await getPublicInfo();
  return (
    <>
      <Bar offline={usingFixtures} />
      <main className={styles.main}>
        <h1 className={styles.h1}>
          Lost money to a crypto scam? <em>We can help you follow it.</em>
        </h1>
        <p className={styles.lede}>
          Hound is free. Tell us what happened and send a picture of your payment. We trace where your money went, tell you
          who can freeze it, and give you a report to send to the police.
        </p>

        <div className={styles.ways}>
          {phone && (
            <a href={`tel:${phone}`} className={styles.way}>
              <span className={styles.wayTitle}>Call us</span>
              <span className={styles.phone}>{formatPhone(phone)}</span>
              <span className={styles.wayText}>A calm voice takes your story and texts you a link. About 5 minutes.</span>
            </a>
          )}
          <Link href="/report" className={styles.way}>
            <span className={styles.wayTitle}>Report online</span>
            <span className={styles.wayText}>Answer a few short questions, then send a screenshot of your payment.</span>
            <span className={styles.wayGo}>Start →</span>
          </Link>
        </div>

        <p className={styles.back}>
          Already reported? <Link href="/c">Check your case with your case code</Link>.
        </p>

        <section className={styles.safe} aria-labelledby="safe-h">
          <h2 id="safe-h">Hound will never</h2>
          <ul>
            <li>ask you for money, a fee, or a &quot;tax&quot; to release funds</li>
            <li>ask for your passwords, seed phrase, recovery phrase or private keys</li>
            <li>promise to get your money back</li>
          </ul>
          <p>
            If anyone offers to recover your money for a fee, that is a second scam. It is one of the most common ones after a
            loss.
          </p>
        </section>

        <p className={styles.small}>
          Hound reads public blockchain data only and never touches funds. What we find is reported, not proven.{" "}
          <Link href="/how">How Hound works</Link>
        </p>
      </main>
    </>
  );
}
