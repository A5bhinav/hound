"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import styles from "../victim.module.css";

type State = { k: "idle" } | { k: "sending" } | { k: "error"; message: string };

/** Online report: the same questions the phone agent asks, then the victim's upload page for this case. */
export default function ReportForm() {
  const router = useRouter();
  const [state, setState] = useState<State>({ k: "idle" });

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const body = Object.fromEntries(["summary", "scam_app", "platform", "first_contact", "exchange_used", "name"].map((k) => [k, String(f.get(k) ?? "")]));
    setState({ k: "sending" });
    let res: Response;
    try {
      res = await fetch("/api/intake/web/start", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(20_000),
      });
    } catch (err) {
      console.error("[hound-web] online report failed:", err);
      return setState({ k: "error", message: "We couldn't send your report. Check your internet connection and try again." });
    }
    const text = await res.text();
    if (!res.ok) {
      console.error(`[hound-web] online report -> ${res.status}: ${text.slice(0, 300)}`);
      return setState({
        k: "error",
        message: res.status === 429 ? "Too many reports from here in the last hour. Please try again later, or call us." : "Something went wrong on our side. Please try again, or call us.",
      });
    }
    const { case_code } = JSON.parse(text) as { case_code: string };
    router.push(`/c/${case_code}`);
  }

  return (
    <form className={styles.form} onSubmit={submit}>
      <label className={styles.field}>
        What happened?
        <span>Who contacted you, what they promised, roughly how much you sent.</span>
        <textarea name="summary" required maxLength={1200} />
      </label>
      <div className={styles.pair}>
        <label className={styles.field}>
          What app or website did you invest through?
          <span>For example the trading app they told you to use.</span>
          <input name="scam_app" maxLength={120} />
        </label>
        <label className={styles.field}>
          How did they first contact you?
          <span>A text, WhatsApp, a dating app, social media…</span>
          <input name="platform" maxLength={120} />
        </label>
        <label className={styles.field}>
          When did it start?
          <span>Month and year.</span>
          <input name="first_contact" type="month" />
        </label>
        <label className={styles.field}>
          Which exchange did you send the money from?
          <span>For example Coinbase, Crypto.com, Kraken.</span>
          <input name="exchange_used" maxLength={80} />
        </label>
      </div>
      <label className={styles.field}>
        Your first name (optional)
        <input name="name" maxLength={40} autoComplete="given-name" />
      </label>
      {state.k === "error" && (
        <p className={styles.error} role="alert">
          {state.message}
        </p>
      )}
      <div className={styles.formFoot}>
        <button type="submit" className={`btn btn-primary btn-lg ${styles.submit}`} disabled={state.k === "sending"}>
          {state.k === "sending" ? "Sending…" : "Next: send a picture of your payment →"}
        </button>
        <span className="small">Only &quot;What happened?&quot; is required.</span>
      </div>
    </form>
  );
}
