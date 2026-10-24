import { Bar } from "@/components/Chrome";
import { usingFixtures } from "@/lib/api";
import styles from "../victim.module.css";
import ReportForm from "./ReportForm";

export const metadata = { title: "Hound: report a scam" };

export default function ReportPage() {
  return (
    <>
      <Bar offline={usingFixtures} />
      <main className={styles.main}>
        <p className="eyebrow">Report a scam · step 1 of 2</p>
        <h1 className={styles.h1}>Tell us what happened</h1>
        <p className={styles.lede}>
          A few short questions. Next you send a screenshot of your payment, and we trace where the money went. Never type a
          password, seed phrase or private key here.
        </p>
        <ReportForm />
      </main>
    </>
  );
}
