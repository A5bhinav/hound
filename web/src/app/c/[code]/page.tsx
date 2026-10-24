import UploadForm, { LinkNotActive } from "@/components/UploadForm";
import { intakeCodeActive } from "@/lib/api";
import styles from "./upload.module.css";

export const metadata = { title: "Hound: send us your payment" };

/** Short link the phone agent reads out and the case card shows as a QR code (AUDIT §5). Victim-facing: no app chrome. */
export default async function UploadPage({ params }: PageProps<"/c/[code]">) {
  const { code } = await params;
  const active = await intakeCodeActive(code);
  return (
    <main className={styles.page}>
      <header className={styles.head}>
        <span className={styles.brand}>Hound</span>
        <span className={styles.code}>Case {code}</span>
      </header>
      {active === false ? (
        <LinkNotActive />
      ) : (
        <>
          <h1 className={styles.h1}>Send us a picture of your payment</h1>
          <UploadForm code={code} />
        </>
      )}
    </main>
  );
}
