import { Bar, DEMO_CASE, NextStep, StepLabel } from "@/components/Chrome";
import ExchangeCheck from "@/components/ExchangeCheck";
import { usingFixtures } from "@/lib/api";

export default function ExchangePage() {
  return (
    <>
      <Bar offline={usingFixtures} step={3} />
      <main className="wrap">
        <header className="page-head">
          <div>
            <StepLabel n={3}>Stop the next victim</StepLabel>
            <h1>
              What an exchange sees
              <br />
              <span className="quiet">when someone tries to pay a wallet from this case</span>
            </h1>
            <p className="sub">Traced wallets on a warning list. The exchange checks before money leaves.</p>
          </div>
        </header>
        {usingFixtures && (
          <p className="notice" role="note" style={{ marginBottom: "1.25rem" }}>
            The exchange check needs the live backend (GET /check). Unset HOUND_DATA to use it.
          </p>
        )}
        <ExchangeCheck />
        <NextStep href={`/cases/${DEMO_CASE}/packet`} label="Police report">
          Send the evidence to the people who can freeze the money.
        </NextStep>
      </main>
    </>
  );
}
