import Link from "next/link";
import BarGlass from "./BarGlass";

/** The Hound mark, traced from the brand sheet (docs/brand/mark.svg). Inline so it takes the text colour. */
export function HoundMark({ className = "wordmark-mark" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 512 261" aria-hidden="true">
      <path fill="currentColor" fillRule="evenodd" d="M0 260 L176 261 L271 191.5 L454.5 206 L512 145.5 L390 113 L369 83.5 L180 0 L197.5 55 L96.5 128 L215.5 102 L88.5 178.5 Z M310.5 102 L359.5 105 L349 123.5 Z" />
    </svg>
  );
}

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

/** The lock + "Read-only · never touches funds": Hound's trust promise. */
export function Secure() {
  return (
    <span className="secure" title="Hound reads public blockchain data only. It never holds, moves or asks for funds or keys.">
      <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
        <rect x="4" y="9" width="12" height="8.5" rx="2" />
        <path d="M7 9V6.5a3 3 0 0 1 6 0V9" />
      </svg>
      Read-only · never touches funds
    </span>
  );
}

/** offline: HOUND_DATA=fixture, serving the repo's examples/ instead of the live backend.
 *  step: on the guided tour (/how and its four steps), the steps row shows under the bar with this one current.
 *  caseId: the case steps 2 and 4 open. */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function Bar({ offline, step, caseId = DEMO_CASE, children }: { offline: boolean; step?: Step; caseId?: string; children?: React.ReactNode }) {
  const current = typeof step === "number" ? step : 0; // steps before this one get a check
  return (
    <>
      <header className="bar">
        <Link href="/" className="wordmark" aria-label="Hound home">
          <HoundMark />
          Hound
        </Link>
        <nav className="bar-nav" aria-label="Main">
          <Link href="/">For Victims</Link>
          <Link href={`/cases/${encodeURIComponent(DEMO_CASE)}/packet`}>For Law Enforcement</Link>
          <Link href="/exchange">For Exchanges</Link>
          <Link href="/how" aria-current={step !== undefined ? "page" : undefined}>How It Works</Link>
        </nav>
        {/* The voice agent tells callers "at the top of the page, press Check my case": keep it here, on every screen. */}
        <Link href="/c" className="btn bar-check">
          Check my case
        </Link>
        <Link href="/report" className="btn btn-primary bar-cta glint">
          Report a scam
        </Link>
        {offline && <span className="sample-flag">OFFLINE · examples/ data, not the live API</span>}
        <BarGlass />
      </header>
      {step !== undefined && (
        <nav className="tour" aria-label="How Hound works">
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
    </>
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

/** A loading screen: the page head it is waiting for, then a calm box saying what is happening. */
export function LoadingPanel({ eyebrow, title, items }: { eyebrow: string; title: string; items: string[] }) {
  return (
    <main className="wrap" role="status" aria-live="polite">
      <header className="page-head">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
        </div>
      </header>
      <div className="notice">
        <ul className="checks">
          {items.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      </div>
    </main>
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
