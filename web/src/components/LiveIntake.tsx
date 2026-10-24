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
export default function LiveIntake({ replayCase, publicBase, phone }: { replayCase: CaseSummary | null; publicBase?: string | null; phone?: string | null }) {
  const [feed, setFeed] = useState<Feed>({ k: "waiting" });
  const replaying = useRef(false);
  const replayTimers = useRef<ReturnType<typeof setTimeout>[]>([]);
  // Last case code the poll returned, and the code that was already active when the replay started.
  // /intake/active keeps any unvalidated session for its whole TTL, so an abandoned call must not end a replay.
  const lastLiveCode = useRef<string | null>(null);
  const replayIgnoreCode = useRef<string | null>(null);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      if (stop) return;
      if (replaying.current) {
        // A replay stays on screen until the presenter leaves it or a NEW call starts (a session whose
        // case code differs from the one already active when the replay began).
        try {
          const res = await fetch("/api/intake/active", { cache: "no-store" });
          if (res.ok && res.status !== 204) {
            const live = (await res.json()) as IntakeSession;
            if (live.case_code !== replayIgnoreCode.current) {
              console.info("[hound-web] new live intake", live.case_code, "started; ending the replay");
              endReplay();
              lastLiveCode.current = live.case_code;
              setFeed({ k: "live", s: live });
            }
          }
        } catch (err) {
          console.error("[hound-web] intake poll failed during replay:", err);
        }
      } else {
        try {
          const res = await fetch("/api/intake/active", { cache: "no-store" });
          if (res.status === 204) {
            lastLiveCode.current = null;
            setFeed({ k: "waiting" });
          } else if (res.ok) {
            const live = (await res.json()) as IntakeSession;
            lastLiveCode.current = live.case_code;
            setFeed({ k: "live", s: live });
          }
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

  function endReplay() {
    replayTimers.current.forEach(clearTimeout);
    replayTimers.current = [];
    replaying.current = false;
  }

  function backToLive() {
    endReplay();
    setFeed({ k: "waiting" }); // the next poll shows a live call if one is in progress
  }

  function replay() {
    if (!replayCase) return;
    endReplay();
    replaying.current = true;
    replayIgnoreCode.current = lastLiveCode.current;
    // The QR must open on a judge's phone: the public host, not this laptop's localhost.
    const base = `${publicBase || window.location.origin}/c/REPLAY`;
    const story = replayCase.story ?? {};
    const frames: IntakeSession[] = [
      { case_code: "REPLAY", upload_url: base, status: "story", story: { platform: story.platform } },
      { case_code: "REPLAY", upload_url: base, status: "story", story: { platform: story.platform, first_contact: story.first_contact }, victim: replayCase.victim },
      { case_code: "REPLAY", upload_url: base, status: "awaiting_upload", story, victim: replayCase.victim },
      { case_code: "REPLAY", upload_url: base, status: "validating", story, victim: replayCase.victim },
      { case_code: "REPLAY", upload_url: base, status: "validated", story, victim: replayCase.victim, case_id: replayCase.case_id },
    ];
    replayTimers.current = frames.map((s, i) => setTimeout(() => setFeed({ k: "replay", s }), i * REPLAY_STEP_MS));
  }

  const s = feed.k === "live" || feed.k === "replay" ? feed.s : null;
  return (
    <div className={styles.wrap}>
      <div className={styles.top}>
        <div>
          <p className="eyebrow">
            Step 1 of 4 · Report the scam{feed.k === "replay" ? " · replay of a recorded call, not a live one" : ""}
          </p>
          <h1 className={styles.h1}>{s ? `Case ${s.case_code}` : "Waiting for a victim to call"}</h1>
        </div>
        {feed.k === "replay" ? (
          <button type="button" className={styles.replay} onClick={backToLive}>
            Back to live
          </button>
        ) : (
          <button type="button" className={styles.replay} onClick={replay} disabled={!replayCase}>
            Play a sample call
          </button>
        )}
      </div>

      {feed.k === "unavailable" && (
        <p className={styles.notice} role="alert">
          {feed.message} Use "Play a sample call" to show the flow.
        </p>
      )}
      {feed.k === "waiting" && (
        <p className={styles.lead}>
          {phone ? (
            <>
              Call <strong className={styles.phone}>{formatPhone(phone)}</strong> to report a scam. The case appears here as you talk.
            </>
          ) : (
            "When someone calls the Hound line, their case appears here as they talk."
          )}
        </p>
      )}

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
                Next: Follow the money →
              </Link>
            )}
            {feed.k === "live" && s.status === "validated" && s.case_id && s.upload_url && (
              // Operator only (upload_url is null beyond localhost): a validated send proves the payment
              // exists, not who made it, so a human approves before the case can cause exchange holds.
              <Approve code={s.case_code} caseId={s.case_id} approved={!!s.approved} />
            )}
          </section>
          {s.status !== "story" &&
            (s.upload_url ? (
              <UploadLink url={s.upload_url} code={s.case_code} sample={feed.k === "replay"} />
            ) : (
              <p className={styles.notice}>The upload link is shown on the operator&apos;s screen.</p>
            ))}
        </div>
      )}
    </div>
  );
}

function Approve({ code, caseId, approved }: { code: string; caseId: string; approved: boolean }) {
  const [st, setSt] = useState<{ k: "idle" | "busy" | "done" } | { k: "error"; message: string }>({ k: approved ? "done" : "idle" });
  if (approved || st.k === "done") return <p className={styles.summary}>Approved: this case can now trigger exchange holds.</p>;
  const go = async () => {
    setSt({ k: "busy" });
    try {
      const res = await fetch(`/api/intake/${encodeURIComponent(code)}/approve`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ case_id: caseId }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        console.error(`[hound-web] approve ${code} -> ${res.status}: ${text.slice(0, 300)}`);
        return setSt({ k: "error", message: res.status === 403 ? "Only the operator's laptop can approve." : `Approve failed (${res.status}).` });
      }
      setSt({ k: "done" });
    } catch (err) {
      console.error(`[hound-web] approve ${code} failed:`, err);
      setSt({ k: "error", message: "Couldn't reach the backend." });
    }
  };
  return (
    <>
      <button type="button" className={styles.go} onClick={go} disabled={st.k === "busy"}>
        {st.k === "busy" ? "Approving…" : "Approve: I reviewed this send"}
      </button>
      {st.k === "error" && <p className={styles.notice} role="alert">{st.message}</p>}
    </>
  );
}

/** +16812755467 reads as (681) 275-5467; anything else is shown as given. */
function formatPhone(p: string) {
  const m = p.replace(/\D/g, "").match(/^1?(\d{3})(\d{3})(\d{4})$/);
  return m ? `(${m[1]}) ${m[2]}-${m[3]}` : p;
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

function UploadLink({ url, code, sample }: { url: string; code: string; sample?: boolean }) {
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
      {sample && <p className={styles.url}>Sample link from the recorded intake. It does not take uploads.</p>}
    </section>
  );
}
