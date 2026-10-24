import type { NextConfig } from "next";

const API_URL = process.env.HOUND_API_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  // Browser code calls /api/* (same origin); Next proxies it to the FastAPI backend (BRIEF §0).
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/:path*` }];
  },
  experimental: {
    // Default is 30 s. A live trace can run to the 120 s deadline (AUDIT N4) while POST /trace is still synchronous.
    proxyTimeout: 150_000,
  },
};

export default nextConfig;
