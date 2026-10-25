import Link from "next/link";
import { Bar, Secure } from "@/components/Chrome";
import HeroMockup from "@/components/HeroMockup";
import { getPublicInfo, usingFixtures } from "@/lib/api";
import styles from "./home.module.css";

export const metadata = { title: "Hound: help after a crypto scam" };

/** +15014431471 reads as (501) 443-1471. */
function formatPhone(p: string) {
  const m = p.replace(/\D/g, "").match(/^1?(\d{3})(\d{3})(\d{4})$/);
  return m ? `(${m[1]}) ${m[2]}-${m[3]}` : p;
}

const ICON = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" } as const;

const FEATURES = [
  {
    title: "Trace",
    text: "We follow your money across blockchains, wallet by wallet.",
    href: "/cases/ohnd-replay-ah",
    icon: (
      <svg viewBox="0 0 40 40" {...ICON}>
        <path d="M17 23l6-6" />
        <path d="M21 13l2.5-2.5a6 6 0 0 1 8.5 8.5L29.5 21.5" />
        <path d="M19 27l-2.5 2.5a6 6 0 0 1-8.5-8.5L10.5 18.5" />
        <circle cx="13" cy="13" r="6.5" />
        <circle cx="27" cy="27" r="6.5" />
      </svg>
    ),
  },
  {
    title: "Warn",
    text: "Exchanges check our warning list before the same wallets scam again.",
    href: "/exchange",
    icon: (
      <svg viewBox="0 0 40 40" {...ICON}>
        <path d="M20 6a9 9 0 0 0-9 9v7l-3 5h24l-3-5v-7a9 9 0 0 0-9-9z" />
        <path d="M16.5 31a3.5 3.5 0 0 0 7 0" />
      </svg>
    ),
  },
  {
    title: "Report",
    text: "You get a clear, one-page report for law enforcement.",
    href: "/cases/ohnd-replay-ah/packet",
    icon: (
      <svg viewBox="0 0 40 40" {...ICON}>
        <path d="M11 5h13l7 7v23H11z" />
        <path d="M24 5v7h7M16 20h10M16 25h10M16 30h6" />
      </svg>
    ),
  },
];

/** The victim's front door: what Hound does in one look, two ways to report, a way back to an open case,
 *  and what Hound will never do. */
export default async function Home() {
  const { phone } = await getPublicInfo();
  return (
    <>
      <Bar offline={usingFixtures} />
      {/* Clip sideways overflow at the screen edge, not the 1600px column, so the card and its glow run to the edge. */}
      <div className={styles.clip}>
      <main className={styles.main} data-home>
        <div className={styles.first}>
        <section className={styles.hero}>
          <div className={styles.copy}>
            <p className={styles.eyebrow}>Trace. Warn. Prevent.</p>
            <h1 className={styles.h1}>
              Lost money to a
              <br />
              crypto scam?
              <br />
              <span className={styles.red}>Let&apos;s track it down.</span>
            </h1>
            <p className={styles.lede}>We trace stolen funds, warn exchanges, and prepare a report for police.</p>
            <div className={styles.ctas}>
              <Link href="/report" className={`btn btn-primary btn-lg glint ${styles.cta}`}>
                Report a scam
                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
                  <path d="M4 10h12m0 0l-4.5-4.5M16 10l-4.5 4.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </Link>
              <Link href="/how" className={`btn btn-lg ${styles.cta}`}>
                See how it works
              </Link>
            </div>
            <Secure />
          </div>
          <HeroMockup />
          <a href="#what" className={styles.scrollCue}>
            Scroll
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
              <path d="M5 8l5 5 5-5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </a>
        </section>

        <section id="what" className={styles.features} aria-label="What Hound does">
          {FEATURES.map((f, n) => (
            <Link key={f.title} href={f.href} className={styles.feature}>
              <span className={styles.num}>{String(n + 1).padStart(2, "0")}</span>
              <span className={styles.fIcon} aria-hidden="true">
                {f.icon}
              </span>
              <span className={styles.fBody}>
                <span className={styles.fTitle}>{f.title}</span>
                <span className={styles.fText}>{f.text}</span>
              </span>
              <svg className={styles.fArrow} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
                <path d="M4 10h12m0 0l-4.5-4.5M16 10l-4.5 4.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </Link>
          ))}
        </section>

        </div>

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
      </div>
    </>
  );
}
