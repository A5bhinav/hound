import { HoundMark } from "@/components/Chrome";
import styles from "./upload.module.css";

export default function Loading() {
  return (
    <main className={styles.page} role="status">
      <header className={styles.head}>
        <span className="wordmark">
          <HoundMark />
          Hound
        </span>
      </header>
      <p className="label">Loading</p>
    </main>
  );
}
