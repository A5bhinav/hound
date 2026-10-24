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
      <main className="wrap">
        <header className="page-head">
          <div>
            <p className="label">Free help after a crypto scam</p>
            <h1>Lost money to a crypto scam? We can help you follow it.</h1>
            <p className="sub">We trace where your money went, who can freeze it, and give you a police report.</p>
          </div>
        </header>

        <div className={`grid g3 ${styles.ways}`}>
          {phone && (
            <a href={`tel:${phone}`} className={`box ${styles.way} ${styles.wayCall}`}>
              <p className="label">Call us</p>
              <span className={styles.phone}>{formatPhone(phone)}</span>
              <ul className="checks">
                <li>A calm voice takes your story</li>
                <li>We tell you our website and walk you through sending a screenshot</li>
                <li>About 5 minutes</li>
              </ul>
              <span className="btn btn-primary">Call now</span>
            </a>
          )}
          <Link href="/report" className={`box ${styles.way}`}>
            <p className="label">Online</p>
            <span className={styles.wayTitle}>Report online</span>
            <ul className="checks">
              <li>A few short questions</li>
              <li>Upload a screenshot of your payment</li>
            </ul>
            <span className="btn">Start →</span>
          </Link>
          <Link href="/c" className={`box ${styles.way}`}>
            <p className="label">Already reported?</p>
            <span className={styles.wayTitle}>Check my case</span>
            <ul className="checks">
              <li>Use the 6-character case code we gave you</li>
            </ul>
            <span className="btn">Check your case with your case code</span>
          </Link>
        </div>

        <div className={`grid g2 ${styles.below}`}>
          <section className="box box-red" aria-labelledby="safe-h">
            <h2 id="safe-h" className={styles.boxTitle}>Hound will never</h2>
            <ul className="checks no">
              <li>Ask you for money, a fee, or a &quot;tax&quot; to release funds</li>
              <li>Ask for your passwords, seed phrase, recovery phrase or private keys</li>
              <li>Promise to get your money back</li>
            </ul>
            <p className={styles.warn}>Anyone offering recovery for a fee is running a second scam.</p>
          </section>
          <section className="box" aria-labelledby="get-h">
            <h2 id="get-h" className={styles.boxTitle}>What you get</h2>
            <ul className="checks ok">
              <li>Where your money went, wallet by wallet</li>
              <li>Who can freeze it: Tether, the exchange, the FBI&apos;s IC3</li>
              <li>A one-page report to send to the police</li>
            </ul>
          </section>
        </div>

        <p className={`small ${styles.foot}`}>
          Public blockchain data only · Reported, not proven · <Link href="/how">How Hound works</Link>
        </p>
      </main>
    </>
  );
}
