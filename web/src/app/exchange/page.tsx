import { Bar, DEMO_CASE, NextStep, StepLabel } from "@/components/Chrome";
import ExchangeCheck from "@/components/ExchangeCheck";
import { usingFixtures } from "@/lib/api";

export default function ExchangePage() {
  return (
    <>
      <Bar offline={usingFixtures} step={3} />
      <header className="page-intro">
        <StepLabel n={3}>Stop the next victim</StepLabel>
        <h1>What an exchange sees when someone tries to pay a wallet from this case</h1>
        <p>
          Every wallet Hound traced goes on a warning list. Before a withdrawal leaves, the exchange asks Hound, and holds the
          payment if the wallet is on the list. Reported, not proven.
        </p>
      </header>
      {usingFixtures && (
        <p className="api-error" role="note">
          The exchange check needs the live backend (GET /check). Unset HOUND_DATA to use it.
        </p>
      )}
      <ExchangeCheck />
      <div className="page-foot">
        <NextStep href={`/cases/${DEMO_CASE}/packet`} label="Police report">
          Send the evidence to the people who can freeze the money.
        </NextStep>
      </div>
    </>
  );
}
