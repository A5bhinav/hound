"use client";

import { useState } from "react";
import { clearTraceCache } from "@/lib/useTrace";

/** DEMO.md step 7: clear traces between judges (POST /demo/reset). Deliberately quiet; second click confirms. */
export default function ResetDemo() {
  const [state, setState] = useState<"idle" | "confirm" | "busy" | "done" | "error">("idle");
  const [msg, setMsg] = useState("");

  async function reset() {
    if (state !== "confirm") return setState("confirm");
    setState("busy");
    try {
      const res = await fetch("/api/demo/reset", { method: "POST" });
      const body = await res.text();
      if (!res.ok) throw new Error(`HTTP ${res.status} ${body.slice(0, 120)}`);
      // The backend forgot its traces; forget ours too, or the next judge sees this one's revealed case.
      clearTraceCache();
      setState("done");
      setMsg("Demo reset: traces cleared, curated cases reloaded.");
    } catch (err) {
      console.error("[hound-web] demo reset failed:", err);
      setState("error");
      setMsg(`Reset failed: ${err}`);
    }
  }

  return (
    <p style={{ marginTop: "3rem", fontSize: "0.75rem", color: "var(--ink-2)", opacity: 0.6 }}>
      <button
        type="button"
        onClick={reset}
        disabled={state === "busy"}
        style={{ font: "inherit", color: "inherit", background: "none", border: 0, padding: 0, cursor: "pointer", textDecoration: "underline" }}
      >
        {state === "confirm" ? "Click again to clear every trace" : "Reset demo"}
      </button>
      {msg && <span role="status"> · {msg}</span>}
    </p>
  );
}
