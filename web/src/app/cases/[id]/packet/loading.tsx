import { Bar } from "@/components/Chrome";

/** Shown while the backend writes the report: instant when it was written ahead, 10 to 25 s when Claude writes it now. */
export default function Loading() {
  return (
    <>
      <Bar offline={false} step={4} />
      <main className="wrap" role="status">
        <header className="page-head">
          <div>
            <p className="eyebrow">Step 4 of 4 · Police report</p>
            <h1>Writing the police report…</h1>
          </div>
          <span className="badge badge-hold">Up to 20 seconds</span>
        </header>
        <ul className="box checks">
          <li>The summary is written from the finished trace</li>
          <li>Every number in it is checked against the trace before it is shown</li>
        </ul>
      </main>
    </>
  );
}
