import Link from "next/link";

/** The demo is one story in four steps; the bar always shows where on it this page sits. */
/** A step of the guided tour; "tour" is its overview page (stepper shown, nothing current). */
export type Step = 1 | 2 | 3 | 4 | "proof" | "tour";

/** The DOJ replay is the case every step links to when the page has no case of its own. */
export const DEMO_CASE = "ohnd-replay-ah";

const STEPS: { n: 1 | 2 | 3 | 4; label: string; href: (caseId: string) => string }[] = [
  { n: 1, label: "Report", href: () => "/intake" },
  { n: 2, label: "Follow the money", href: (c) => `/cases/${encodeURIComponent(c)}` },
  { n: 3, label: "Stop the next victim", href: () => "/exchange" },
  { n: 4, label: "Police report", href: (c) => `/cases/${encodeURIComponent(c)}/packet` },
];

/** offline: HOUND_DATA=fixture, serving the repo's examples/ instead of the live backend.
 *  step: which step this page is (highlighted). caseId: the case steps 2 and 4 open. */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function Bar({ offline, step, caseId = DEMO_CASE, children }: { offline: boolean; step?: Step; caseId?: string; children?: React.ReactNode }) {
  const current = typeof step === "number" ? step : 0; // steps before this one get a check
  return (
    <header className="bar">
      <Link href="/" className="wordmark">
        Hound
      </Link>
      <span className="bar-secure" title="Hound reads public blockchain data only. It never holds, moves or asks for funds or keys.">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
          <rect x="3" y="7" width="10" height="7" rx="1.5" />
          <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" />
        </svg>
        Read-only · never touches funds
      </span>
      {step === undefined ? (
        <nav className="bar-nav" aria-label="Main">
          <Link href="/report">Report a scam</Link>
          <Link href="/c">Check my case</Link>
          <Link href="/how">How Hound works</Link>
        </nav>
      ) : (
      <nav className="bar-nav" aria-label="How Hound works">
        <ol className="steps">
          {STEPS.map((s) => (
            <li key={s.n}>
              <Link href={s.href(caseId)} aria-current={step === s.n ? "step" : undefined}>
                <span className="step-n" aria-hidden="true">{s.n < current ? "✓" : s.n}</span>
                {s.label}
              </Link>
            </li>
          ))}
        </ol>
        <Link href="/proof" className="proof-link" aria-current={step === "proof" ? "page" : undefined}>
          Proof it works
        </Link>
      </nav>
      )}
      {offline && <span className="sample-flag">OFFLINE · examples/ data, not the live API</span>}
    </header>
  );
}

/** One clear way forward at the bottom of each step. */
export function NextStep({ href, label, children }: { href: string; label: string; children?: React.ReactNode }) {
  return (
    <nav className="next-step" aria-label="Next step">
      <Link href={href} className="next-step-link">
        Next: {label} <span aria-hidden="true">→</span>
      </Link>
      {children && <p className="next-step-why">{children}</p>}
    </nav>
  );
}

/** "Step 2 of 4 · Follow the money" above a page title: where this page sits in the story. */
export function StepLabel({ n, children }: { n: 1 | 2 | 3 | 4; children: React.ReactNode }) {
  return (
    <p className="eyebrow">
      Step {n} of 4 · {children}
    </p>
  );
}

export function ApiError({ message }: { message: string }) {
  return (
    <div className="api-error" role="alert">
      <p className="eyebrow">Couldn&apos;t load from the Hound API</p>
      <p>{message}</p>
    </div>
  );
}
