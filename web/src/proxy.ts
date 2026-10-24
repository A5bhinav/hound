import { NextResponse, type NextRequest } from "next/server";

/** The /api rewrites proxy browser requests to the backend. When the backend sits behind a free ngrok
 *  domain, ngrok answers browser user agents with a warning page instead of the API; this header skips it.
 *  Harmless for any other backend. */
export function proxy(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.set("ngrok-skip-browser-warning", "1");
  return NextResponse.next({ request: { headers } });
}

export const config = { matcher: "/api/:path*" };
