// Server-only data access. Never import from a "use client" file:
// HOUND_API_URL and HOUND_DATA are not exposed to the browser.
import { readFile } from "node:fs/promises";
import path from "node:path";
import { connection } from "next/server";
import type { Case, CaseSummary, Trace } from "./types";

const API_URL = process.env.HOUND_API_URL || "http://localhost:8000";

/** HOUND_DATA=fixture serves the repo's examples/ files instead of calling the backend. */
export const usingFixtures = process.env.HOUND_DATA === "fixture";

// next dev / next start run from web/, so the repo root is one level up.
const EXAMPLES = path.join(process.cwd(), "..", "examples");

export class HoundApiError extends Error {}

async function call<T>(method: "GET" | "POST", apiPath: string): Promise<T> {
  // Backend data is live: render at request time, never bake it (or an error) into the build.
  await connection();
  const url = `${API_URL}${apiPath}`;
  let res: Response;
  try {
    res = await fetch(url, { method, cache: "no-store" });
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

async function example<T>(name: string): Promise<T> {
  const file = path.join(EXAMPLES, name);
  try {
    return JSON.parse(await readFile(file, "utf8")) as T;
  } catch (err) {
    console.error(`[hound-web] reading ${file} failed:`, err);
    throw new HoundApiError(`Fixture mode couldn't read ${file}: ${err}. Pull main to get examples/.`);
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

export async function traceCase(id: string): Promise<Trace> {
  if (usingFixtures) {
    const trace = await example<Trace>("ohnd_replay.trace.json");
    if (trace.case_id !== id) throw new HoundApiError(`Fixture mode only has case "${trace.case_id}".`);
    return trace;
  }
  return call<Trace>("POST", `/cases/${encodeURIComponent(id)}/trace`);
}
