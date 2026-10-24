"use client";

import Link from "next/link";
import QRCode from "qrcode";
import { useEffect, useRef, useState } from "react";
import type { CaseSummary, IntakeSession } from "@/lib/types";
import styles from "./LiveIntake.module.css";

const POLL_MS = 1000;
const REPLAY_STEP_MS = 1400;

type Feed =
  | { k: "waiting" } // backend up, no call in progress
  | { k: "live"; s: IntakeSession }
  | { k: "replay"; s: IntakeSession }
  | { k: "unavailable"; message: string };

const STEPS: { status: IntakeSession["status"][]; label: string }[] = [
  { status: ["story", "awaiting_upload", "validating", "needs_retake", "validated"], label: "Story taken on the call" },
  { status: ["awaiting_upload", "validating", "needs_retake", "validated"], label: "Case code read out, upload link shown" },
  { status: ["validating", "needs_retake", "validated"], label: "Screenshot received" },
  { status: ["validated"], label: "Send confirmed on chain" },
];

/** Polls GET /intake/active (AUDIT §5). Replay plays the same steps from a curated case, no backend involved. */
export default function LiveIntake({ replayCase }: { replayCase: CaseSummary | null }) {
  const [feed, setFeed] = useState<Feed>({ k: "waiting" });
  const replaying = useRef(false);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      if (stop) return;
      if (!replaying.current) {
        try {
          const res = await fetch("/api/intake/active", { cache: "no-store" });
          if (res.status === 204) setFeed({ k: "waiting" });
          else if (res.ok) setFeed({ k: "live", s: (await res.json()) as IntakeSession });
          else {
            const body = (await res.text()).slice(0, 160);
            const why =
              res.status === 404
                ? "The intake backend isn't running yet (GET /intake/active returned 404)."
                : `GET /intake/active returned ${res.status}. ${body}`;
            if (res.status >= 500) console.error("[hound-web] intake poll:", res.status, body);
            setFeed({ k: "unavailable", message: why });
          }
        } catch (err) {
          console.error("[hound-web] intake poll failed:", err);
          setFeed({ k: "unavailable", message: `Couldn't reach the web server: ${err}` });
        }
      }
      timer = setTimeout(tick, POLL_MS);
    };
    void tick();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, []);

  function replay() {
    if (!replayCase) return;
    replaying.current = true;
    const base = `${window.location.origin}/c/REPLAY`;
    const story = replayCase.story ?? {};
    const frames: IntakeSession[] = [
      { case_code: "REPLAY", upload_url: base, status: "story", story: { platform: story.platform } },
      { case_code: "REPLAY", upload_url: base, status: "story", story: { platform: story.platform, first_contact: story.first_contact }, victim: replayCase.victim },
      { case_code: "REPLAY", upload_url: base, status: "awaiting_upload", story, victim: replayCase.victim },
      { case_code: "REPLAY", upload_url: base, status: "validating", story, victim: replayCase.victim },
      { case_code: "REPLAY", upload_url: base, status: "validated", story, victim: replayCase.victim, case_id: replayCase.case_id },
    ];
    frames.forEach((s, i) =>
      setTimeout(() => {
        setFeed({ k: "replay", s });
        if (i === frames.length - 1) setTimeout(() => (replaying.current = false), 15000);
      }, i * REPLAY_STEP_MS),
    );
  }

  const s = feed.k === "live" || feed.k === "replay" ? feed.s : null;
  return (
    <div className={styles.wrap}>
      <div className={styles.top}>
        <div>
          <p className="eyebrow">{feed.k === "replay" ? "Replay of a recorded intake, not a live call" : "Live intake"}</p>
          <h1 className={styles.h1}>{s ? `Case ${s.case_code}` : "Waiting for a call"}</h1>
        </div>
        <button type="button" className={styles.replay} onClick={replay} disabled={!replayCase || feed.k === "replay"}>
          Replay intake
        </button>
      </div>

      {feed.k === "unavailable" && (
        <p className={styles.notice} role="alert">
          {feed.message} Use Replay intake to show the flow.
        </p>
      )}
      {feed.k === "waiting" && <p className={styles.lead}>When someone calls the Hound line, their case appears here as they talk.</p>}

      {s && (
        <div className={styles.grid}>
          <section className={styles.card} aria-live="polite">
            <ol className={styles.steps}>
              {STEPS.map((st) => (
                <li key={st.label} data-done={st.status.includes(s.status) || undefined}>
                  {st.label}
                </li>
              ))}
            </ol>
            <dl className={styles.facts}>
              <Fact k="Who" v={s.victim?.alias} />
              <Fact k="Age" v={s.victim?.age_band} />
              <Fact k="Sent from" v={s.victim?.exchange_used} />
              <Fact k="Scam app" v={s.story?.scam_app} />
              <Fact k="Contacted on" v={s.story?.platform} />
              <Fact k="First contact" v={s.story?.first_contact} />
            </dl>
            {s.story?.summary && <p className={styles.summary}>{s.story.summary}</p>}
            {s.status === "needs_retake" && s.message && (
              <p className={styles.notice} role="alert">
                Asked for another picture: {s.message}
              </p>
            )}
            {s.status === "validated" && s.case_id && (
              <Link href={`/cases/${encodeURIComponent(s.case_id)}`} className={styles.go}>
                Trace this case →
              </Link>
            )}
          </section>
          {s.status !== "story" && <UploadLink url={s.upload_url} code={s.case_code} />}
        </div>
      )}
    </div>
  );
}

function Fact({ k, v }: { k: string; v?: string | null }) {
  if (!v || v === "unknown") return null;
  return (
    <div className={styles.fact}>
      <dt>{k}</dt>
      <dd>{v}</dd>
    </div>
  );
}

function UploadLink({ url, code }: { url: string; code: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    QRCode.toDataURL(url, { margin: 1, width: 240 })
      .then(setSrc)
      .catch((e: unknown) => {
        console.error("[hound-web] QR generation failed:", e);
        setErr(String(e));
      });
  }, [url]);
  return (
    <section className={styles.qr}>
      <p className="eyebrow">Upload link for the caller</p>
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element -- data: URL generated in the browser
        <img src={src} width={240} height={240} alt={`QR code for ${url}`} />
      ) : (
        <p className={styles.notice}>{err ? `QR code failed: ${err}` : "Making the QR code…"}</p>
      )}
      <p className={styles.url}>{url.replace(/^https?:\/\//, "")}</p>
      <p className={styles.codeBig}>{code}</p>
    </section>
  );
}
