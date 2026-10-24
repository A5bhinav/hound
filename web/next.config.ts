import type { NextConfig } from "next";

const API_URL = process.env.HOUND_API_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  // e2e builds into its own folder so it never clobbers the demo's .next (and its baked API port).
  distDir: process.env.HOUND_NEXT_DIST_DIR || ".next",
  cacheComponents: true,
  partialPrefetching: true,
  // Browser code calls /api/... (same origin); Next proxies it to the FastAPI backend (BRIEF §0).
  // Only the routes the browser needs, so the public web origin doesn't expose the whole backend.
  // Everything else (GET /cases, ...) is fetched server-side in src/lib/api.ts.
  async rewrites() {
    return [
      { source: "/api/cases/:id/trace", destination: `${API_URL}/cases/:id/trace` },
      { source: "/api/traces/:id", destination: `${API_URL}/traces/:id` },
      // Exchange hold screen (query string ?chain=&address= is passed through).
      { source: "/api/check", destination: `${API_URL}/check` },
      // DEMO.md step 7: reset between judges.
      { source: "/api/demo/reset", destination: `${API_URL}/demo/reset` },
      // Intake (CK): the live case card polls the active call; the victim's upload page posts the screenshot.
      { source: "/api/intake/active", destination: `${API_URL}/intake/active` },
      { source: "/api/intake/:code/screenshot", destination: `${API_URL}/intake/:code/screenshot` },
      // Operator approves a validated intake case so it can feed holds (local only; the backend checks).
      { source: "/api/intake/:code/approve", destination: `${API_URL}/intake/:code/approve` },
      // Cartesia's tool call reaches the backend through the same public host (token checked by the backend).
      { source: "/api/intake/voice/story", destination: `${API_URL}/intake/voice/story` },
    ];
  },
  experimental: {
    // Default is 30 s. A live trace can run to the 120 s deadline (AUDIT N4) while POST /trace is still synchronous.
    proxyTimeout: 150_000,
  },
};

export default nextConfig;
