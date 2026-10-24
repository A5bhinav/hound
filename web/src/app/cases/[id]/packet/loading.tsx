import { Bar, LoadingPanel } from "@/components/Chrome";

/** Shown while the backend writes the report: instant when it was written ahead, 10 to 25 s when Claude writes it now. */
export default function Loading() {
  return (
    <>
      <Bar offline={false} step={4} />
      <LoadingPanel eyebrow="Step 4 of 4 · Police report" title="Writing the police report…" items={["This can take up to 20 seconds", "The summary is written from the finished trace", "Every number in it is checked against the trace before it is shown"]} />
    </>
  );
}
