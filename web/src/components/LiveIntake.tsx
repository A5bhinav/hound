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

/** One or two words per intake status, for the status tile. */
const STATUS: Record<IntakeSession["status"], string> = {
  story: "On the call",
  awaiting_upload: "Awaiting picture",
  validating: "Checking",
  needs_retake: "Retake asked",
  validated: "Confirmed",
};

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
  const done = s ? STEPS.filter((st) => st.status.includes(s.status)).length : 0;
  return (
    <main className="wrap">
      <header className="page-head">
        <div>
          <p className="eyebrow">
            Step 1 of 4 · Report the scam{feed.k === "replay" ? " · replay of a recorded call, not a live one" : ""}
          </p>
          <h1>{s ? `Case ${s.case_code}` : "Waiting for a victim to call"}</h1>
          <div className={`ctas ${styles.headCta}`}>
            {feed.k === "replay" ? (
              <button type="button" className="btn btn-lg" onClick={backToLive}>
                Back to live
              </button>
            ) : (
              <button type="button" className="btn btn-primary btn-lg" onClick={replay} disabled={!replayCase}>
                Play a sample call
              </button>
            )}
          </div>
        </div>
      </header>

      {feed.k === "unavailable" && (
        <p className={`box ${styles.notice}`} role="alert">
          {feed.message} Use &quot;Play a sample call&quot; to show the flow.
        </p>
      )}

      <div className={`grid g4 ${styles.tiles}`}>
        <div className={`box ${styles.tile}`}>
          <p className="label">Hotline</p>
          {phone ? (
            <a href={`tel:${phone}`} className={`stat-n ${styles.phone}`}>
              {formatPhone(phone)}
            </a>
          ) : (
            <span className="stat-n">Not set</span>
          )}
          <span className="stat-l">The case appears here as they talk</span>
        </div>
        <div className={`box ${styles.tile}`}>
          <p className="label">Case code</p>
          <span className={`stat-n ${s ? styles.code : ""}`}>{s ? s.case_code : "None yet"}</span>
          <span className="stat-l">Read out to the caller twice</span>
        </div>
        <div className={`box ${styles.tile}`}>
          <p className="label">Status</p>
          <span className="stat-n">{s ? STATUS[s.status] : feed.k === "unavailable" ? "Offline" : "Waiting"}</span>
          <span className="stat-l">{done} of {STEPS.length} steps done</span>
        </div>
        <div className={`box ${styles.tile}`}>
          <p className="label">Feed</p>
          <span className="stat-n">{feed.k === "replay" ? "Sample" : feed.k === "live" ? "Live call" : "Listening"}</span>
          <span className="stat-l">
            {feed.k === "replay" ? (
              <span className="badge badge-hold">Recorded call, not live</span>
            ) : (
              <span className="badge badge-ok">Checks every second</span>
            )}
          </span>
        </div>
      </div>

      <div className={`grid g3 ${styles.grid}`}>
        <section className="box" aria-labelledby="progress-h" aria-live="polite">
          <div className="box-h">
            <h2 id="progress-h">Intake progress</h2>
            <span className={`badge ${done === STEPS.length ? "badge-ok" : ""}`}>
              {done} / {STEPS.length}
            </span>
          </div>
          <ol className={styles.steps}>
            {STEPS.map((st) => (
              <li key={st.label} data-done={(s && st.status.includes(s.status)) || undefined}>
                {st.label}
              </li>
            ))}
          </ol>
          {s?.status === "needs_retake" && s.message && (
            <p className={styles.notice} role="alert">
              Asked for another picture: {s.message}
            </p>
          )}
          {s?.status === "validated" && s.case_id && (
            <Link href={`/cases/${encodeURIComponent(s.case_id)}`} className={`btn btn-primary btn-lg ${styles.go}`}>
              Next: Follow the money →
            </Link>
          )}
          {feed.k === "live" && s?.status === "validated" && s.case_id && s.upload_url && (
            // Operator only (upload_url is null beyond localhost): a validated send proves the payment
            // exists, not who made it, so a human approves before the case can cause exchange holds.
            <Approve code={s.case_code} caseId={s.case_id} approved={!!s.approved} />
          )}
        </section>

        <section className="box" aria-labelledby="caller-h">
          <div className="box-h">
            <h2 id="caller-h">Case card</h2>
            {s && <span className="badge">{feed.k === "replay" ? "From the recorded call" : "From the call"}</span>}
          </div>
          {s ? (
            <dl className={`kv ${styles.facts}`}>
              <Fact k="Who" v={s.victim?.alias} />
              <Fact k="Age" v={s.victim?.age_band} />
              <Fact k="Sent from" v={s.victim?.exchange_used} />
              <Fact k="Scam app" v={s.story?.scam_app} />
              <Fact k="Contacted on" v={s.story?.platform} />
              <Fact k="First contact" v={s.story?.first_contact} />
            </dl>
          ) : (
            <p className="small">Fills in as the caller talks.</p>
          )}
          {s?.story?.summary && (
            <div className={styles.summary}>
              <p className="label">Story</p>
              <p>{s.story.summary}</p>
            </div>
          )}
        </section>

        {s && s.status !== "story" ? (
          s.upload_url ? (
            <UploadLink url={s.upload_url} code={s.case_code} sample={feed.k === "replay"} />
          ) : (
            <section className="box">
              <h2 className={styles.boxTitle}>Upload link</h2>
              <p className="small">The upload link is shown on the operator&apos;s screen.</p>
            </section>
          )
        ) : (
          <section className="box" aria-labelledby="upload-h">
            <h2 id="upload-h" className={styles.boxTitle}>Upload link</h2>
            <ul className="checks">
              <li>Appears once the case code is read out</li>
              <li>The caller opens it on their phone</li>
              <li>They send a screenshot of the payment</li>
            </ul>
          </section>
        )}
      </div>
    </main>
  );
}

function Approve({ code, caseId, approved }: { code: string; caseId: string; approved: boolean }) {
  const [st, setSt] = useState<{ k: "idle" | "busy" | "done" } | { k: "error"; message: string }>({ k: approved ? "done" : "idle" });
  if (approved || st.k === "done") return <p className={`badge badge-ok ${styles.approved}`}>Approved: this case can now trigger exchange holds.</p>;
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
      <button type="button" className={`btn ${styles.go}`} onClick={go} disabled={st.k === "busy"}>
        {st.k === "busy" ? "Approving…" : "Approve: I reviewed this send"}
      </button>
      {st.k === "error" && <p className={styles.notice} role="alert">{st.message}</p>}
    </>
  );
}

/** +19898008367 reads as (989) 800-8367; anything else is shown as given. */
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
    <section className={`box ${styles.qr}`} aria-labelledby="upload-h">
      <div className="box-h">
        <h2 id="upload-h">Upload link for the caller</h2>
        {sample && <span className="badge badge-hold">Sample</span>}
      </div>
      <div className={styles.qrBody}>
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element -- data: URL generated in the browser
          <img src={src} width={168} height={168} alt={`QR code for ${url}`} className={styles.qrImg} />
        ) : (
          <p className={styles.notice}>{err ? `QR code failed: ${err}` : "Making the QR code…"}</p>
        )}
        <div>
          <p className="label">Case code</p>
          <p className={styles.codeBig}>{code}</p>
          <p className="small">Scan to open the upload page</p>
        </div>
      </div>
      <p className="label">Link</p>
      <p className={styles.url}>{url.replace(/^https?:\/\//, "")}</p>
      {sample && <p className={`small ${styles.sampleNote}`}>Sample link from the recorded intake. It does not take uploads.</p>}
    </section>
  );
}
