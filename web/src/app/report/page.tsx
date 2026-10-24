import { Bar } from "@/components/Chrome";
import { usingFixtures } from "@/lib/api";
import styles from "../victim.module.css";
import ReportForm from "./ReportForm";

export const metadata = { title: "Hound: report a scam" };

export default function ReportPage() {
  return (
    <>
      <Bar offline={usingFixtures} />
      <main className="wrap">
        <header className="page-head">
          <div>
            <p className="label">Report a scam · step 1 of 2</p>
            <h1>Tell us what happened</h1>
            <p className="sub">A few short questions. Then a picture of your payment.</p>
          </div>
        </header>

        <div className={`grid g3 ${styles.reportGrid}`}>
          <section className="box span2" aria-label="Your report">
            <ReportForm />
          </section>
          <aside className={styles.side}>
            <section className="box" aria-labelledby="next-h">
              <h2 id="next-h" className={styles.boxTitle}>What happens next</h2>
              <ol className={styles.nextList}>
                <li>You answer a few short questions</li>
                <li>You send a screenshot of your payment</li>
                <li>We trace where the money went</li>
                <li>You get a case code to check your case</li>
              </ol>
            </section>
            <section className="box box-red" aria-labelledby="never-h">
              <h2 id="never-h" className={styles.boxTitle}>Never type here</h2>
              <ul className="checks no">
                <li>A password</li>
                <li>A seed phrase or recovery phrase</li>
                <li>A private key</li>
              </ul>
              <p className={styles.warn}>Hound never asks for money or a fee. Anyone who does is running a second scam.</p>
            </section>
          </aside>
        </div>
      </main>
    </>
  );
}
