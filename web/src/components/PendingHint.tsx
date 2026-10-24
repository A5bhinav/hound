"use client";

import { useLinkStatus } from "next/link";

/** Inside a <Link>: says the packet is being written while the navigation is pending (Claude takes 10-25 s). */
export default function PendingHint() {
  const { pending } = useLinkStatus();
  return pending ? <span aria-live="polite"> · writing…</span> : null;
}
