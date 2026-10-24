import { NextResponse, type NextRequest } from "next/server";

const LOOPBACK = new Set(["127.0.0.1", "::1", "::ffff:127.0.0.1"]);

/** The /api rewrites proxy browser requests to the backend. When the backend sits behind a free ngrok
 *  domain, ngrok answers browser user agents with a warning page instead of the API; this header skips it.
 *  Harmless for any other backend.
 *
 *  Having a proxy at all makes Next add X-Forwarded-For with the socket address (127.0.0.1 on the operator
 *  laptop). The backend reads any X-Forwarded-For as "came through a tunnel" and refuses localhost-only
 *  actions (Approve, Reset demo, unredacted live cases), so drop only those loopback entries Next added.
 *  A real visitor's address is kept, and tunnels still add cf-connecting-ip / X-Forwarded-Host. */
export function proxy(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.set("ngrok-skip-browser-warning", "1");
  const xff = headers.get("x-forwarded-for");
  if (xff !== null) {
    const kept = xff.split(",").map((s) => s.trim()).filter((s) => s && !LOOPBACK.has(s));
    if (kept.length) {
      headers.set("x-forwarded-for", kept.join(", "));
    } else {
      headers.delete("x-forwarded-for");
      headers.delete("x-forwarded-port");
      headers.delete("x-forwarded-proto");
    }
  }
  return NextResponse.next({ request: { headers } });
}

export const config = { matcher: "/api/:path*" };
