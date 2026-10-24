// Server-only data access. Never import from a "use client" file:
// HOUND_API_URL and HOUND_DATA are not exposed to the browser.
import { connection } from "next/server";
import type { Case, Trace } from "./types";
import sampleCase from "@/fixtures/sample.case.json";
import sampleTrace from "@/fixtures/sample.trace.json";

const API_URL = process.env.HOUND_API_URL || "http://localhost:8000";

/** HOUND_DATA=fixture serves the placeholder files in src/fixtures instead of calling the backend. */
export const usingFixtures = process.env.HOUND_DATA === "fixture";

export class HoundApiError extends Error {}

async function call<T>(method: "GET" | "POST", path: string): Promise<T> {
  // Backend data is live: render at request time, never bake it (or an error) into the build.
  await connection();
  const url = `${API_URL}${path}`;
  let res: Response;
  try {
    res = await fetch(url, { method, cache: "no-store" });
  } catch (err) {
    console.error(`[hound-web] ${method} ${url} failed:`, err);
    throw new HoundApiError(
      `Can't reach the Hound API at ${API_URL} (${method} ${path}). Start the backend, or set HOUND_DATA=fixture in web/.env.local to use sample data.`,
    );
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    console.error(`[hound-web] ${method} ${url} -> ${res.status}: ${body.slice(0, 500)}`);
    throw new HoundApiError(`${method} ${path} returned ${res.status}. ${body.slice(0, 300)}`);
  }
  return (await res.json()) as T;
}

export async function listCases(): Promise<Case[]> {
  if (usingFixtures) return [sampleCase as Case];
  return call<Case[]>("GET", "/cases");
}

export async function getCase(id: string): Promise<Case> {
  // §8.5 has no GET /cases/{id}; pick it out of the curated list.
  const found = (await listCases()).find((c) => c.case_id === id);
  if (!found) throw new HoundApiError(`No case "${id}" in GET /cases.`);
  return found;
}

export async function traceCase(id: string): Promise<Trace> {
  if (usingFixtures) {
    if (id !== sampleCase.case_id) throw new HoundApiError(`Fixture mode only has case "${sampleCase.case_id}".`);
    return sampleTrace as Trace;
  }
  return call<Trace>("POST", `/cases/${encodeURIComponent(id)}/trace`);
}
