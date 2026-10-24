import { Bar } from "@/components/Chrome";

/** Shown while the backend writes the report: instant when it was written ahead, 10 to 25 s when Claude writes it now. */
export default function Loading() {
  return (
    <>
      <Bar offline={false} step={4} />
      <header className="page-intro" role="status">
        <p className="eyebrow">Step 4 of 4 · Police report</p>
        <h1>Writing the police report…</h1>
        <p>This can take up to 20 seconds. Every number in it is checked against the trace before it is shown.</p>
      </header>
    </>
  );
}
