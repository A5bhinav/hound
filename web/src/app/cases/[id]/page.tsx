import { ApiError, Bar } from "@/components/Chrome";
import CaseView from "@/components/CaseView";
import { HoundApiError, fixtureTrace, getCase, usingFixtures } from "@/lib/api";
import type { Case, CaseSummary, Trace } from "@/lib/types";

export default async function CasePage({ params }: PageProps<"/cases/[id]">) {
  const { id } = await params;
  let c: CaseSummary | Case;
  // Fixture mode has the finished trace on disk; otherwise the browser starts and polls it via /api.
  let initialTrace: Trace | null = null;
  try {
    c = await getCase(id);
    if (usingFixtures) initialTrace = await fixtureTrace(id);
  } catch (err) {
    if (!(err instanceof HoundApiError)) throw err;
    return (
      <>
        <Bar offline={usingFixtures} />
        <ApiError message={err.message} />
      </>
    );
  }

  return (
    <>
      <Bar offline={usingFixtures}>
        {c.source === "doj_replay" ? "Replay · " : ""}
        {c.victim?.alias ?? c.case_id}
      </Bar>
      <CaseView c={c} initialTrace={initialTrace} />
    </>
  );
}
