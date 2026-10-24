import { Bar } from "@/components/Chrome";
import UploadForm, { LinkNotActive } from "@/components/UploadForm";
import { intakeCodeActive, usingFixtures } from "@/lib/api";
import styles from "./upload.module.css";

export const metadata = { title: "Hound: send us your payment" };

/** Short link the phone agent reads out and the case card shows as a QR code (AUDIT §5). Victim-facing: one column, one action. */
export default async function UploadPage({ params }: PageProps<"/c/[code]">) {
  const { code: raw } = await params;
  const code = raw.toUpperCase(); // the backend upper-cases codes too
  const active = await intakeCodeActive(code);
  return (
    <>
      <Bar offline={usingFixtures} />
      <main className={styles.page}>
        <p className="eyebrow">
          Case <span className={styles.code}>{code}</span>
        </p>
        {active === false ? (
          <LinkNotActive />
        ) : (
          // The heading lives in UploadForm so a 404 on upload can hide it along with the form.
          <UploadForm code={code} heading={<h1 className={styles.h1}>Send us a picture of your payment</h1>} />
        )}
      </main>
    </>
  );
}
