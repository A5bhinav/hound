import type { NextConfig } from "next";

const API_URL = process.env.HOUND_API_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  // Browser code calls /api/... (same origin); Next proxies it to the FastAPI backend (BRIEF §0).
  // Only the routes the browser needs, so the public web origin doesn't expose the whole backend.
  // Everything else (GET /cases, ...) is fetched server-side in src/lib/api.ts.
  async rewrites() {
    return [
      { source: "/api/cases/:id/trace", destination: `${API_URL}/cases/:id/trace` },
      { source: "/api/traces/:id", destination: `${API_URL}/traces/:id` },
    ];
  },
  experimental: {
    // Default is 30 s. A live trace can run to the 120 s deadline (AUDIT N4) while POST /trace is still synchronous.
    proxyTimeout: 150_000,
  },
};

export default nextConfig;
