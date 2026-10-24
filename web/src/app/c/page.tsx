import { Bar } from "@/components/Chrome";
import { usingFixtures } from "@/lib/api";
import CodeEntry from "./CodeEntry";
import styles from "./[code]/upload.module.css";

export const metadata = { title: "Hound: enter your case code" };

/** For a caller who is not in the room: the phone agent reads out a six-letter code; they type it here
 *  and land on their case page (/my/{code}). Same victim-facing column as the upload page. */
export default function CodePage() {
  return (
    <>
      <Bar offline={usingFixtures} />
      <main className={styles.page}>
        <p className="eyebrow">Already reported?</p>
        <h1 className={styles.h1}>Check your case</h1>
        <p className={`lede ${styles.sub}`}>Type the case code from the phone call or your online report.</p>
        <CodeEntry />
      </main>
    </>
  );
}
