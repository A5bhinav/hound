"use client";

import { useRef, useState } from "react";
import type { IntakeUploadResult } from "@/lib/types";
import styles from "./UploadForm.module.css";

type State =
  | { k: "idle" }
  | { k: "sending" }
  | { k: "done"; caseId: string }
  | { k: "retake"; message: string }
  | { k: "error"; message: string; detail: string }
  | { k: "inactive" };

/** Unknown or expired code (sessions last 2 hours): plain words, never the raw HTTP error (review F7). */
export function LinkNotActive() {
  return (
    <div className={styles.done} role="alert">
      <p className={styles.big}>This link is not active.</p>
      <p>It may have expired, or the code may be mistyped. Ask the person on the phone for a new link.</p>
    </div>
  );
}

/** The victim's upload page (AUDIT N7): one big button, 18px+ text, ARIA, and a "type it instead" field. */
export default function UploadForm({ code, heading }: { code: string; heading?: React.ReactNode }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<State>({ k: "idle" });
  const [typed, setTyped] = useState("");
  const [showTyped, setShowTyped] = useState(false);

  async function send(body: FormData) {
    setState({ k: "sending" });
    let res: Response;
    try {
      res = await fetch(`/api/intake/${encodeURIComponent(code)}/screenshot`, { method: "POST", body });
    } catch (err) {
      console.error("[hound-web] upload failed:", err);
      return setState({ k: "error", message: "We couldn't send it. Check your internet connection and try again.", detail: String(err) });
    }
    const text = await res.text();
    if (res.status === 404) {
      console.error(`[hound-web] upload -> 404 for code ${code}: ${text.slice(0, 300)}`);
      return setState({ k: "inactive" });
    }
    if (!res.ok) {
      console.error(`[hound-web] upload -> ${res.status}: ${text.slice(0, 300)}`);
      return setState({
        k: "error",
        message: "Something went wrong on our side. Please try again, or tell the person on the phone.",
        detail: `HTTP ${res.status} ${text.slice(0, 200)}`,
      });
    }
    let r: IntakeUploadResult;
    try {
      r = JSON.parse(text) as IntakeUploadResult;
    } catch {
      return setState({ k: "error", message: "Something went wrong on our side. Please try again.", detail: `Not JSON: ${text.slice(0, 200)}` });
    }
    if (r.status === "validated") setState({ k: "done", caseId: r.case_id });
    else setState({ k: "retake", message: r.message });
  }

  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    void send(fd);
    e.target.value = ""; // allow choosing the same picture again after a retake
  }

  function onTyped(e: React.FormEvent) {
    e.preventDefault();
    const fd = new FormData();
    fd.append("typed", typed.trim());
    void send(fd);
  }

  if (state.k === "inactive") return <LinkNotActive />;

  if (state.k === "done") {
    return (
      <>
        {heading}
        <div className={styles.done} role="status" aria-live="polite">
          <p className={styles.big}>Thank you. We found your payment.</p>
          <p>You can tell the person on the phone you&apos;re done. We&apos;ll follow where the money went.</p>
          <p className={styles.small}>Your case number is {code}.</p>
        </div>
      </>
    );
  }

  return (
    <>
      {heading}
      <div className={styles.wrap}>
        <ol className={styles.steps}>
          <li>Open the app you used to send the money.</li>
          <li>Find that payment and take a screenshot of it.</li>
          <li>Press the big button below and choose that picture.</li>
        </ol>

        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          className={styles.hidden}
          onChange={onFile}
          aria-hidden="true"
          tabIndex={-1}
        />
        <button
          type="button"
          className={styles.cta}
          onClick={() => fileRef.current?.click()}
          disabled={state.k === "sending"}
          aria-describedby="upload-status"
        >
          {state.k === "sending" ? "Sending your picture…" : "Choose the picture of my payment"}
        </button>

        <div id="upload-status" className={styles.status} role="status" aria-live="polite">
          {state.k === "retake" && (
            <p className={styles.retake}>
              <strong>We need another picture.</strong> {state.message}
            </p>
          )}
          {state.k === "error" && (
            <p className={styles.error}>
              <strong>{state.message}</strong>
              <span className={styles.small}>{state.detail}</span>
            </p>
          )}
        </div>

        {!showTyped ? (
          <button type="button" className={styles.link} onClick={() => setShowTyped(true)}>
            I can&apos;t take a picture. Let me type it instead.
          </button>
        ) : (
          <form className={styles.typed} onSubmit={onTyped}>
            <label htmlFor="typed">
              Type what you can see about the payment: the long code that starts with 0x, the address you sent to, and the amount.
            </label>
            <textarea id="typed" rows={4} value={typed} onChange={(e) => setTyped(e.target.value)} spellCheck={false} />
            <button type="submit" className={styles.secondary} disabled={!typed.trim() || state.k === "sending"}>
              Send what I typed
            </button>
          </form>
        )}

        <p className={styles.small}>We will never ask for your password, your PIN, or your recovery words.</p>
      </div>
    </>
  );
}
