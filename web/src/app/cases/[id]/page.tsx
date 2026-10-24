import CaseCard from "@/components/CaseCard";
import { ApiError, Bar } from "@/components/Chrome";
import TraceGraph from "@/components/TraceGraph";
import { HoundApiError, getCase, traceCase, usingFixtures } from "@/lib/api";
import type { Case, CaseSummary, Trace } from "@/lib/types";
import styles from "./case.module.css";

export default async function CasePage({ params }: PageProps<"/cases/[id]">) {
  const { id } = await params;
  let c: CaseSummary | Case, trace: Trace;
  try {
    [c, trace] = await Promise.all([getCase(id), traceCase(id)]);
  } catch (err) {
    if (!(err instanceof HoundApiError)) throw err;
    return (
      <>
        <Bar offline={usingFixtures} />
        <ApiError message={err.message} />
      </>
    );
  }

  const asOf = "as_of" in c ? c.as_of : null;
  return (
    <>
      <Bar offline={usingFixtures}>
        {trace.replay ? "Replay · " : ""}
        {c.victim?.alias ?? c.case_id}
      </Bar>
      {trace.status !== "done" && (
        <p className={styles.note} role="alert">
          Trace {trace.status === "partial" ? "stopped early (partial)" : "failed"}. What&apos;s shown is everything the engine
          reached; see the endpoints for why each branch stopped.
        </p>
      )}
      <main className={styles.layout}>
        <CaseCard c={c} trace={trace} />
        <TraceGraph trace={trace} asOf={asOf} />
      </main>
    </>
  );
}
