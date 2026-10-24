import { Bar } from "@/components/Chrome";
import LiveIntake from "@/components/LiveIntake";
import { getPublicBase, HoundApiError, listCases, usingFixtures } from "@/lib/api";
import type { CaseSummary } from "@/lib/types";

export default async function IntakePage() {
  // The replay button plays the intake steps from the curated DOJ replay case.
  let replayCase: CaseSummary | null = null;
  try {
    replayCase = (await listCases()).find((c) => c.source === "doj_replay") ?? null;
  } catch (err) {
    if (!(err instanceof HoundApiError)) throw err;
    console.error("[hound-web] intake page: no replay case:", err.message);
  }
  return (
    <>
      <Bar offline={usingFixtures}>Intake</Bar>
      <LiveIntake replayCase={replayCase} publicBase={await getPublicBase()} />
    </>
  );
}
