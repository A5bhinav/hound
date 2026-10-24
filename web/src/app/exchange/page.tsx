import { Bar } from "@/components/Chrome";
import ExchangeCheck from "@/components/ExchangeCheck";
import { usingFixtures } from "@/lib/api";

export default function ExchangePage() {
  return (
    <>
      <Bar offline={usingFixtures}>Exchange withdrawal check</Bar>
      {usingFixtures && (
        <p className="api-error" role="note">
          The exchange check needs the live backend (GET /check). Unset HOUND_DATA to use it.
        </p>
      )}
      <ExchangeCheck />
    </>
  );
}
