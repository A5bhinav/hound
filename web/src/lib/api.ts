// Server-only data access. Never import from a "use client" file:
// HOUND_API_URL and HOUND_DATA are not exposed to the browser.
import { readFile } from "node:fs/promises";
import path from "node:path";
import { headers } from "next/headers";
import { connection } from "next/server";
import type { Case, CaseSummary, Trace } from "./types";

const API_URL = process.env.HOUND_API_URL || "http://localhost:8000";

/** HOUND_DATA=fixture serves the repo's examples/ files instead of calling the backend. */
export const usingFixtures = process.env.HOUND_DATA === "fixture";

// next dev / next start run from web/, so the repo root is one level up.
const EXAMPLES = path.join(process.cwd(), "..", "examples");

export class HoundApiError extends Error {}

// The backend redacts live cases for anyone beyond localhost by reading these headers. Server pages
// fetch from loopback, so without forwarding them a tunnel viewer would look local and see full data.
const FORWARD = ["cf-connecting-ip", "x-forwarded-for", "x-real-ip", "forwarded", "true-client-ip"];

async function viewerHeaders(): Promise<Record<string, string>> {
  const h = await headers();
  const out: Record<string, string> = { "ngrok-skip-browser-warning": "1" }; // see src/proxy.ts
  for (const k of FORWARD) {
    const v = h.get(k);
    if (v) out[k] = v;
  }
  const host = h.get("x-forwarded-host") || h.get("host");
  if (host) out["x-forwarded-host"] = host;
  return out;
}

async function call<T>(method: "GET" | "POST", apiPath: string): Promise<T> {
  // Backend data is live: render at request time, never bake it (or an error) into the build.
  await connection();
  const url = `${API_URL}${apiPath}`;
  let res: Response;
  try {
    res = await fetch(url, { method, cache: "no-store", headers: await viewerHeaders() });
  } catch (err) {
    console.error(`[hound-web] ${method} ${url} failed:`, err);
    throw new HoundApiError(
      `Can't reach the Hound API at ${API_URL} (${method} ${apiPath}). Start the backend, or set HOUND_DATA=fixture in web/.env.local to use examples/.`,
    );
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    console.error(`[hound-web] ${method} ${url} -> ${res.status}: ${body.slice(0, 500)}`);
    throw new HoundApiError(`${method} ${apiPath} returned ${res.status}. ${body.slice(0, 300)}`);
  }
  return (await res.json()) as T;
}

/**
 * Is this upload code a live intake session? false on 404 (unknown or expired, sessions live 2 h).
 * null when the backend can't say (unreachable, 5xx): the page then shows the form and the upload reports the error.
 */
export async function intakeCodeActive(code: string): Promise<boolean | null> {
  if (usingFixtures) return true;
  await connection();
  const url = `${API_URL}/intake/${encodeURIComponent(code)}`;
  try {
    const res = await fetch(url, { cache: "no-store", headers: await viewerHeaders() });
    if (res.status === 404) return false;
    if (res.ok) return true;
    console.error(`[hound-web] GET ${url} -> ${res.status}: ${(await res.text().catch(() => "")).slice(0, 300)}`);
    return null;
  } catch (err) {
    console.error(`[hound-web] GET ${url} failed:`, err);
    return null;
  }
}

async function example<T>(name: string): Promise<T> {
  const file = path.join(EXAMPLES, name);
  try {
    return JSON.parse(await readFile(file, "utf8")) as T;
  } catch (err) {
    console.error(`[hound-web] reading ${file} failed:`, err);
    throw new HoundApiError(`Fixture mode couldn't read ${file}: ${err}. Pull main to get examples/.`);
  }
}

/** From the backend's /health: the public web host (PUBLIC_BASE_URL) and the Hound phone line, or nulls. */
export async function getPublicInfo(): Promise<{ base: string | null; phone: string | null }> {
  if (usingFixtures) return { base: null, phone: null };
  try {
    const h = await call<{ public_base_url?: string | null; phone_number?: string | null }>("GET", "/health");
    return { base: h.public_base_url ?? null, phone: h.phone_number ?? null };
  } catch (err) {
    console.error("[hound-web] public info from /health:", err);
    return { base: null, phone: null };
  }
}

export async function listCases(): Promise<CaseSummary[]> {
  if (usingFixtures) return [await example<Case>("ohnd_replay.case.json")];
  return call<CaseSummary[]>("GET", "/cases");
}

/** Full Case in fixture mode; the summary from GET /cases otherwise (the API has no GET /cases/{id}). */
export async function getCase(id: string): Promise<CaseSummary | Case> {
  const found = (await listCases()).find((c) => c.case_id === id);
  if (!found) throw new HoundApiError(`No case "${id}" in the case list.`);
  return found;
}

/** GET /proof/scoreboard, /proof/backtest, /scan/latest (CK). Fields the proof page reads. */
export interface Scoreboard {
  case: string;
  docket: string;
  source_pdf: string;
  trace_source: string | null;
  targets: { label: string; address: string; group: "intermediate" | "final"; reached: boolean }[];
  amount: { label: string; address: string; doj_ah_para74_usdt: number; ours_attributed_usdt: number | null; pct_error: number | null; band: string }[];
  holdout: string[];
  /** The victim-side addresses the engine was given (where the sends start and land). */
  inputs?: { label: string; address: string }[];
  context: { para83_85_totals_usdt?: Record<string, number | string>; note?: string };
  summary: {
    status: string;
    refused_reason: string | null;
    intermediates_reached: number;
    intermediates_total: number;
    finals_reached: number;
    finals_total: number;
    blind: boolean;
    start_disclosure: string;
  };
}

export interface Backtest {
  status?: string;
  n: number;
  n_skipped?: number;
  population?: number;
  detection_lag_median_h: number | null;
  p90_h: number | null;
  escape_share_median: number | null;
  method: string;
}

export interface Scan {
  status?: string;
  label: string;
  scanned_at?: string;
  addresses: number;
  usdt_unfrozen: number;
  addresses_unfrozen: number;
  already_frozen?: number;
  cases: { address: string; chain?: string; category?: string; balance_usdt: number; is_frozen: boolean; freezable_now?: boolean }[];
  method?: string;
}

export async function getProof(): Promise<{ scoreboard: Scoreboard; backtest: Backtest; scan: Scan }> {
  if (usingFixtures) throw new HoundApiError("The proof panel reads the backend (GET /proof/*, /scan/latest). Unset HOUND_DATA to use it.");
  const [scoreboard, backtest, scan] = await Promise.all([
    call<Scoreboard>("GET", "/proof/scoreboard"),
    call<Backtest>("GET", "/proof/backtest"),
    call<Scan>("GET", "/scan/latest"),
  ]);
  return { scoreboard, backtest, scan };
}

export interface Packet {
  /** text is null (redacted: true) for a live case viewed beyond localhost: the prose quotes the victim's story. */
  packet: {
    text: string | null;
    cited: string[];
    source?: string;
    redacted?: boolean;
    citations_verified?: { verified: number; total: number } | boolean;
  };
  trace: Trace;
}

/** What a case code's holder may see: its status and, once validated, the case it created. Null for an unknown code. */
export interface IntakeStatus {
  case_code: string;
  status: "story" | "awaiting_upload" | "validating" | "validated" | "needs_retake";
  message?: string | null;
  case_id?: string | null;
  exchange_used?: string | null;
}

export async function getIntakeStatus(code: string): Promise<IntakeStatus | null> {
  if (usingFixtures) return null;
  try {
    return await call<IntakeStatus>("GET", `/intake/${encodeURIComponent(code)}`);
  } catch (err) {
    if (err instanceof HoundApiError && err.message.includes("returned 404")) return null;
    throw err;
  }
}

/** GET /cases/{id}/packet. Null when there is nothing to write yet (409 no finished trace, 422 nothing traced).
 *  code: the victim's own case code, which unlocks their full report beyond localhost. */
export async function getPacket(id: string, audience: "detective" | "victim", code?: string): Promise<Packet | null> {
  if (usingFixtures) throw new HoundApiError("The packet is written by the backend (GET /cases/{id}/packet). Unset HOUND_DATA to use it.");
  try {
    const own = code ? `&code=${encodeURIComponent(code)}` : "";
    return await call<Packet>("GET", `/cases/${encodeURIComponent(id)}/packet?audience=${audience}${own}`);
  } catch (err) {
    // 409: no finished trace yet. 422: the trace has no endpoints to write about (e.g. a judge's wrong hash).
    if (err instanceof HoundApiError && /returned (409|422)/.test(err.message)) return null;
    throw err;
  }
}

/** Fixture mode only. Live traces are started and polled from the browser (useTrace) via the /api proxy. */
export async function fixtureTrace(id: string): Promise<Trace> {
  const trace = await example<Trace>("ohnd_replay.trace.json");
  if (trace.case_id !== id) throw new HoundApiError(`Fixture mode only has case "${trace.case_id}".`);
  return trace;
}
