import { HoundMark } from "@/components/Chrome";
import CodeEntry from "./CodeEntry";
import styles from "./[code]/upload.module.css";

export const metadata = { title: "Hound: enter your case code" };

/** For a caller who is not in the room: the phone agent reads out a six-letter code; they type it here
 *  and land on their upload page (/c/{code}). Same victim-facing chrome as the upload page. */
export default function CodePage() {
  return (
    <main className={styles.page}>
      <header className={styles.head}>
        <span className="wordmark">
          <HoundMark />
          Hound
        </span>
      </header>
      <h1 className={styles.h1}>Check your case</h1>
      <p className={styles.sub}>Type the case code from the phone call or your online report.</p>
      <CodeEntry />
    </main>
  );
}
