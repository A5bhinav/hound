"use client";

import { useEffect, useState } from "react";
import type { AuditEntry, Trace, TraceRunning } from "./types";

const POLL_MS = 1000;
const GIVE_UP_MS = 180_000; // live deadline is 120 s (AUDIT N4); leave headroom
const MAX_POLL_FAILURES = 3;

export type TraceState =
  | { phase: "running"; log: AuditEntry[]; traceId: string | null; startedAt: number }
  | { phase: "done"; trace: Trace }
  | { phase: "error"; message: string };

// One POST per case per page load: React dev mode runs effects twice, and each POST starts a full backend trace.
const starts = new Map<string, Promise<Trace | TraceRunning>>();

function startTrace(caseId: string): Promise<Trace | TraceRunning> {
  let p = starts.get(caseId);
  if (!p) {
    // Not tied to a component's AbortSignal, so a remount reuses it instead of starting another run.
    p = getJson<Trace | TraceRunning>("POST", `/api/cases/${encodeURIComponent(caseId)}/trace`, new AbortController().signal);
    starts.set(caseId, p);
    p.finally(() => setTimeout(() => starts.delete(caseId), 5000)).catch(() => {});
  }
  return p;
}

const isFinished =(x: Trace | TraceRunning): x is Trace => x.status !== "running" && Array.isArray((x as Trace).nodes);

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
 * Works with both backend shapes: a synchronous POST that returns the finished Trace,
 * and the async one (POST returns {trace_id, status:"running"}, then poll GET /traces/{id}).
 * initial: an already-finished trace (fixture mode), so nothing is fetched.
 */
export function useTrace(caseId: string, initial: Trace | null): TraceState {
  const [state, setState] = useState<TraceState>(() =>
    initial ? { phase: "done", trace: initial } : { phase: "running", log: [], traceId: null, startedAt: Date.now() },
  );

  useEffect(() => {
    if (initial) return;
    const ctl = new AbortController();
    const fail = (err: unknown) => {
      if (ctl.signal.aborted) return;
      console.error("[hound-web] trace failed:", err);
      setState({ phase: "error", message: err instanceof Error ? err.message : String(err) });
    };

    (async () => {
      const startedAt = Date.now();
      const first = await startTrace(caseId);
      if (ctl.signal.aborted) return;
      if (isFinished(first)) return setState({ phase: "done", trace: first });
      if (!first.trace_id) throw new Error(`POST /trace returned neither a Trace nor a trace_id: ${JSON.stringify(first).slice(0, 200)}`);

      let failures = 0;
      while (!ctl.signal.aborted) {
        if (Date.now() - startedAt > GIVE_UP_MS)
          throw new Error(`Trace ${first.trace_id} was still running after ${GIVE_UP_MS / 1000} s. Check the backend log.`);
        await new Promise((r) => setTimeout(r, POLL_MS));
        try {
          const now = await getJson<Trace | TraceRunning>("GET", `/api/traces/${encodeURIComponent(first.trace_id)}`, ctl.signal);
          failures = 0;
          if (isFinished(now)) return setState({ phase: "done", trace: now });
          setState({ phase: "running", log: now.audit_log ?? [], traceId: first.trace_id, startedAt });
        } catch (err) {
          if (ctl.signal.aborted) return;
          failures += 1;
          console.warn(`[hound-web] poll ${failures}/${MAX_POLL_FAILURES} failed:`, err);
          if (failures >= MAX_POLL_FAILURES) throw err;
        }
      }
    })().catch(fail);

    return () => ctl.abort();
  }, [caseId, initial]);

  return state;
}
