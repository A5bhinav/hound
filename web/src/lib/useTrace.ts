"use client";

import { useEffect, useState } from "react";
import type { AuditEntry, Trace, TraceFailed, TraceJob, TraceRunning } from "./types";

const POLL_MS = 1000;
const GIVE_UP_MS = 180_000; // live deadline is 120 s (AUDIT N4); leave headroom
const MAX_POLL_FAILURES = 3;

export type TraceState =
  | { phase: "running"; log: AuditEntry[]; traceId: string | null; startedAt: number }
  | { phase: "done"; trace: Trace }
  | { phase: "error"; message: string };

// One POST per case per page load: React dev mode runs effects twice, and each POST starts a full backend trace.
const starts = new Map<string, Promise<TraceJob>>();

/** "?code=…" when the victim's own case code is known: the backend then returns their trace unshortened. */
const own = (code?: string) => (code ? `?code=${encodeURIComponent(code)}` : "");

function startTrace(caseId: string, code?: string): Promise<TraceJob> {
  let p = starts.get(caseId);
  if (!p) {
    // Not tied to a component's AbortSignal, so a remount reuses it instead of starting another run.
    p = getJson<TraceJob>("POST", `/api/cases/${encodeURIComponent(caseId)}/trace${own(code)}`, new AbortController().signal);
    starts.set(caseId, p);
    p.finally(() => setTimeout(() => starts.delete(caseId), 5000)).catch(() => {});
  }
  return p;
}

// Last finished trace per case, so navigating back (e.g. from the packet) shows it without re-POSTing (H8).
const finished = new Map<string, Trace>();

// Freezes revealed per trace_id, so coming back doesn't hide what the presenter already revealed.
const FREEZES_KEY = "hound:freezesShown:";

export function readFreezesShown(traceId: string): boolean {
  try {
    return sessionStorage.getItem(FREEZES_KEY + traceId) === "1";
  } catch {
    return false;
  }
}

export function writeFreezesShown(traceId: string, shown: boolean) {
  try {
    if (shown) sessionStorage.setItem(FREEZES_KEY + traceId, "1");
    else sessionStorage.removeItem(FREEZES_KEY + traceId);
  } catch (err) {
    console.warn("[hound-web] couldn't persist the freeze reveal:", err);
  }
}

/** Demo reset: forget every cached trace and revealed state, so the next judge starts clean (G3). */
export function clearTraceCache() {
  finished.clear();
  starts.clear();
  try {
    for (const k of Object.keys(sessionStorage)) if (k.startsWith(FREEZES_KEY)) sessionStorage.removeItem(k);
  } catch (err) {
    console.warn("[hound-web] couldn't clear the freeze reveals:", err);
  }
}

class JobFailed extends Error {}

/** The finished Trace, or null while running. Throws JobFailed when the backend reports the job failed. */
function settle(job: TraceJob): Trace | null {
  if (job.status === "error") throw new JobFailed(`The backend trace failed: ${(job as TraceFailed).error}`);
  if (job.status === "running") return null;
  if (!Array.isArray((job as Trace).nodes))
    throw new JobFailed(`Unexpected trace response (status ${job.status}, no nodes): ${JSON.stringify(job).slice(0, 200)}`);
  return job as Trace;
}

const progressOf = (job: TraceRunning & { audit_log?: AuditEntry[] }) => job.audit_log_so_far ?? job.audit_log ?? [];

async function getJson<T>(method: "GET" | "POST", path: string, signal: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { method, signal, cache: "no-store" });
  } catch (err) {
    if (signal.aborted) throw err;
    throw new Error(`Couldn't reach the web server for ${method} ${path}: ${err}`);
  }
  if (!res.ok) {
    const body = (await res.text().catch(() => "")).slice(0, 300);
    const hint = res.status >= 500 ? " Is the backend running at HOUND_API_URL?" : "";
    throw new Error(`${method} ${path} returned ${res.status}.${hint} ${body}`);
  }
  return (await res.json()) as T;
}

/**
 * Starts a trace through the /api proxy and follows it to the end.
 * POST returns a job view ({trace_id, status: "running", audit_log_so_far}); poll GET /traces/{trace_id}
 * until it is the finished Trace or {status: "error"}. A synchronous POST returning the Trace also works.
 * initial: an already-finished trace (fixture mode), so nothing is fetched.
 * A trace this page already finished for the case is reused until Reset demo clears it.
 */
export function useTrace(caseId: string, initial: Trace | null, code?: string): TraceState {
  const [state, setState] = useState<TraceState>(() => {
    const done = initial ?? finished.get(caseId);
    return done ? { phase: "done", trace: done } : { phase: "running", log: [], traceId: null, startedAt: Date.now() };
  });

  useEffect(() => {
    if (initial || finished.has(caseId)) return;
    const finish = (trace: Trace) => {
      finished.set(caseId, trace);
      setState({ phase: "done", trace });
    };
    const ctl = new AbortController();
    const fail = (err: unknown) => {
      if (ctl.signal.aborted) return;
      console.error("[hound-web] trace failed:", err);
      setState({ phase: "error", message: err instanceof Error ? err.message : String(err) });
    };

    (async () => {
      const startedAt = Date.now();
      const first = await startTrace(caseId, code);
      if (ctl.signal.aborted) return;
      const done = settle(first);
      if (done) return finish(done);
      if (!first.trace_id) throw new Error(`POST /trace returned no trace_id: ${JSON.stringify(first).slice(0, 200)}`);
      setState({ phase: "running", log: progressOf(first as TraceRunning), traceId: first.trace_id, startedAt });

      let failures = 0;
      while (!ctl.signal.aborted) {
        if (Date.now() - startedAt > GIVE_UP_MS)
          throw new Error(`Trace ${first.trace_id} was still running after ${GIVE_UP_MS / 1000} s. Check the backend log.`);
        await new Promise((r) => setTimeout(r, POLL_MS));
        let now: TraceJob;
        try {
          now = await getJson<TraceJob>("GET", `/api/traces/${encodeURIComponent(first.trace_id)}${own(code)}`, ctl.signal);
          failures = 0;
        } catch (err) {
          if (ctl.signal.aborted) return;
          failures += 1;
          console.warn(`[hound-web] poll ${failures}/${MAX_POLL_FAILURES} failed:`, err);
          if (failures >= MAX_POLL_FAILURES) throw err;
          continue;
        }
        const result = settle(now); // a failed job throws here: reported at once, not retried
        if (result) return finish(result);
        setState({ phase: "running", log: progressOf(now as TraceRunning), traceId: first.trace_id, startedAt });
      }
    })().catch(fail);

    return () => ctl.abort();
  }, [caseId, initial]);

  return state;
}
