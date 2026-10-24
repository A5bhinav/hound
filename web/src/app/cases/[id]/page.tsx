import CaseCard from "@/components/CaseCard";
import { ApiError, Bar } from "@/components/Chrome";
import TraceGraph from "@/components/TraceGraph";
import { HoundApiError, getCase, traceCase, usingFixtures } from "@/lib/api";
import type { Case, Trace } from "@/lib/types";
import styles from "./case.module.css";

export default async function CasePage({ params }: PageProps<"/cases/[id]">) {
  const { id } = await params;
  let c: Case, trace: Trace;
  try {
    [c, trace] = await Promise.all([getCase(id), traceCase(id)]);
  } catch (err) {
    if (!(err instanceof HoundApiError)) throw err;
    return (
      <>
        <Bar sample={usingFixtures} />
        <ApiError message={err.message} />
      </>
    );
  }

  return (
    <>
      <Bar sample={usingFixtures || Boolean(trace._sample)}>
        {c.victim.alias} · {c.sends[0]?.chain ?? "—"}
      </Bar>
      {trace._sample && <p className={styles.sampleNote}>{trace._sample}</p>}
      <main className={styles.layout}>
        <CaseCard c={c} trace={trace} />
        <TraceGraph trace={trace} />
      </main>
    </>
  );
}
