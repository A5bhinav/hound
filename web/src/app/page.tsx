import Link from "next/link";
import { Bar, Secure } from "@/components/Chrome";
import HeroMockup from "@/components/HeroMockup";
import { getPublicInfo, usingFixtures } from "@/lib/api";
import styles from "./home.module.css";

export const metadata = { title: "Hound: help after a crypto scam" };

/** +16812755467 reads as (681) 275-5467. */
function formatPhone(p: string) {
  const m = p.replace(/\D/g, "").match(/^1?(\d{3})(\d{3})(\d{4})$/);
  return m ? `(${m[1]}) ${m[2]}-${m[3]}` : p;
}

/** The victim's front door: what Hound does in one look, two ways to report, a way back to an open case,
 *  and what Hound will never do. */
export default async function Home() {
  const { phone } = await getPublicInfo();
  return (
    <>
      <Bar offline={usingFixtures} />
      <main className={styles.main}>
        <section className={styles.hero}>
          <div className={styles.copy}>
            <p className={styles.eyebrow}>Trace. Warn. Prevent.</p>
            <h1 className={styles.h1}>
              Lost money to
              <br />a crypto scam?
              <br />
              <span className={styles.quiet}>We help you follow it.</span>
            </h1>
            <p className={styles.lede}>See where your money went, who can freeze it, and get a report for the police.</p>
            <div className={styles.ctas}>
              <Link href="/report" className={`btn btn-primary btn-lg ${styles.cta}`}>
                Report a scam
                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
                  <path d="M4 10h12m0 0l-4.5-4.5M16 10l-4.5 4.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </Link>
              <Link href="/how" className={`btn btn-lg ${styles.cta}`}>
                How it works
              </Link>
            </div>
            <Secure />
          </div>
          <HeroMockup />
        </section>

        <section className={styles.features} aria-label="What Hound does">
          <div>
            <svg className={styles.fIcon} viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <circle cx="14" cy="14" r="9" />
              <path d="M21 21l7 7" strokeLinecap="round" />
            </svg>
            <h2>Trace your funds</h2>
            <p>We map where your money went, wallet by wallet, across the blockchain.</p>
          </div>
          <div>
            <svg className={styles.fIcon} viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M16 3l11 4v8c0 7-4.7 12.2-11 14-6.3-1.8-11-7-11-14V7z" strokeLinejoin="round" />
            </svg>
            <h2>Warn exchanges</h2>
            <p>Exchanges check our warning list before the same wallets can be used to scam others.</p>
          </div>
          <div>
            <svg className={styles.fIcon} viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M8 3h11l6 6v20H8z" strokeLinejoin="round" />
              <path d="M19 3v6h6M12 16h9M12 21h9" strokeLinecap="round" />
            </svg>
            <h2>Get a police report</h2>
            <p>You receive a clear, one-page report with the key evidence for law enforcement.</p>
          </div>
        </section>

        <section className={styles.ways} aria-label="Ways to get help">
          {phone && (
            <a href={`tel:${phone}`} className={`box ${styles.way} ${styles.wayCall}`}>
              <p className="label">Call us</p>
              <span className={styles.wayBig}>{formatPhone(phone)}</span>
              <p className={styles.wayText}>A calm voice takes your story, then tells you our website and walks you through sending a screenshot.</p>
              <span className="btn btn-primary">Call now</span>
            </a>
          )}
          <Link href="/report" className={`box ${styles.way}`}>
            <p className="label">Online</p>
            <span className={styles.wayBig}>Report online</span>
            <p className={styles.wayText}>A few short questions, then a screenshot of your payment.</p>
            <span className="btn">Start →</span>
          </Link>
          <Link href="/c" className={`box ${styles.way}`}>
            <p className="label">Already reported?</p>
            <span className={styles.wayBig}>Check my case</span>
            <p className={styles.wayText}>Use the 6-character case code we gave you.</p>
            <span className="btn">Check →</span>
          </Link>
        </section>

        <section className={`box box-red ${styles.never}`} aria-labelledby="never-h">
          <h2 id="never-h">Hound will never</h2>
          <ul className="checks no">
            <li>Ask you for money, a fee, or a &quot;tax&quot; to release funds</li>
            <li>Ask for your passwords, seed phrase, recovery phrase or private keys</li>
            <li>Promise to get your money back</li>
          </ul>
          <p>Anyone offering recovery for a fee is running a second scam.</p>
        </section>

        <p className={`small ${styles.foot}`}>Public blockchain data only · Reported, not proven</p>
      </main>
    </>
  );
}
