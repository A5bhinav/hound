import Link from "next/link";
import PendingHint from "@/components/PendingHint";
import { ApiError, Bar, NextStep } from "@/components/Chrome";
import PrintButton from "@/components/PrintButton";
import { HoundApiError, getPacket, usingFixtures, type Packet } from "@/lib/api";
import { pct, shortAddr, tok, usdt } from "@/lib/format";
import type { Trace } from "@/lib/types";
import styles from "./packet.module.css";

const REASON_CONTACT: Record<string, string> = {
  exchange: "the exchange's compliance team",
  holding: "Tether (freeze request)",
  frozen: "Tether (already frozen; ask about release to victims)",
  tether_destroyed: "Tether (funds destroyed and reissued)",
};

export default async function PacketPage({ params, searchParams }: PageProps<"/cases/[id]/packet">) {
  const { id } = await params;
  const sp = await searchParams;
  const audience = sp.audience === "victim" ? "victim" : "detective";
  // A victim opening their own report from their case page carries their case code.
  const code = typeof sp.code === "string" ? sp.code : undefined;
  let data: Packet | null;
  try {
    data = await getPacket(id, audience, code);
  } catch (err) {
    if (!(err instanceof HoundApiError)) throw err;
    return (
      <>
        <Bar offline={usingFixtures} step={code ? undefined : 4} caseId={id} />
        <ApiError message={err.message} />
      </>
    );
  }
  const caseHref = `/cases/${encodeURIComponent(id)}`;
  if (!data) {
    return (
      <>
        <Bar offline={usingFixtures} step={code ? undefined : 4} caseId={id} />
        <main className="wrap">
          <div className="notice" role="status">
            <p className="label">No finished trace yet</p>
            <p>
              The packet is written from the latest finished trace. <Link href={caseHref}>Run the trace for {id}</Link>, then come back.
            </p>
          </div>
        </main>
      </>
    );
  }

  const { packet, trace } = data;
  const frozen = trace.endpoints.filter((p) => trace.nodes.find((x) => x.address === p.address)?.frozen?.is_frozen).length;
  const cv = packet.citations_verified;
  // The victim's own copy (opened with their case code, or the victim version): plain words, no trace jargon.
  const plain = !!code || audience === "victim";
  return (
    <>
      <div className={styles.screenOnly}>
        <Bar offline={usingFixtures} step={code ? undefined : 4} caseId={id} />
      </div>
      <div className={`wrap ${styles.page}`}>
        <div className={`${styles.tools} ${styles.screenOnly}`}>
          <Link href={code ? `/my/${code}` : caseHref} className={styles.back}>
            {code ? "← Back to your case" : "← Back to the trace"}
          </Link>
          <span className={styles.toggle} role="group" aria-label="Packet version">
            <Link href={`?audience=detective${code ? `&code=${code}` : ""}`} aria-current={audience === "detective" ? "page" : undefined}>
              {code ? "Copy for the police" : "For the detective"}
              <PendingHint />
            </Link>
            <Link href={`?audience=victim${code ? `&code=${code}` : ""}`} aria-current={audience === "victim" ? "page" : undefined}>
              {code ? "Your copy" : "For the victim"}
              <PendingHint />
            </Link>
          </span>
          <span className={styles.toolBadges}>
            {trace.replay ? <span className="badge badge-ice">Replay</span> : <span className="badge">Live case</span>}
            <span className="badge badge-red">Reported, not proven</span>
          </span>
          <PrintButton />
        </div>

        {/* The victim's copy speaks plainly; the detective's keeps the trace terms. */}
        <div className={`${styles.stats} ${styles.screenOnly}`}>
          <div className={styles.stat}>
            <span className="stat-n">{trace.edges.length}</span>
            <span className="stat-l">{plain ? "Transfers we followed" : "Transfers traced"}</span>
          </div>
          <div className={styles.stat}>
            <span className="stat-n">{trace.endpoints.length}</span>
            <span className="stat-l">{plain ? "Places your money went" : "Places the money stopped"}</span>
          </div>
          <div className={styles.stat}>
            <span className={`stat-n ${frozen ? styles.ice : ""}`}>{frozen}</span>
            <span className="stat-l">Frozen by Tether</span>
          </div>
          {packet.text === null ? (
            <div className={styles.stat}>
              <span className="stat-n">Hidden</span>
              <span className="stat-l">Summary shown on the operator&apos;s screen only</span>
            </div>
          ) : plain ? (
            verified(cv) && (
              <div className={styles.stat}>
                <span className={`stat-n ${styles.ok}`}>Checked</span>
                <span className="stat-l">Every number checked against the blockchain</span>
              </div>
            )
          ) : (
            <div className={styles.stat}>
              <span className="stat-n">{typeof cv === "object" ? `${cv.verified} of ${cv.total}` : packet.cited.length}</span>
              <span className="stat-l">{verified(cv) ? "Cited numbers checked against the trace" : "Cited fields, not verified"}</span>
            </div>
          )}
        </div>

        <main className={styles.sheet}>
          <header className={styles.head}>
            <div>
              <p className="eyebrow">
                {code
                  ? `Your Hound report · ${audience === "detective" ? "copy for the police" : "your copy"}`
                  : `Step 4 of 4 · Police report · ${audience === "detective" ? "copy for the detective" : "copy for the victim"}`}
              </p>
              <h1>{trace.replay ? "Replay of a historical case" : "Scam funds trace"}</h1>
            </div>
            <p className={styles.stamp}>Reported, not proven</p>
          </header>
          <dl className={styles.meta}>
            <div>
              <dt>Case</dt>
              <dd className="mono">{trace.case_id}</dd>
            </div>
            <div>
              <dt>Trace</dt>
              <dd className="mono">{trace.trace_id}</dd>
            </div>
            <div>
              <dt>Generated</dt>
              <dd>{trace.created_at.slice(0, 10)}</dd>
            </div>
            {packet.source && (
              <div>
                <dt>Written by</dt>
                <dd>{packet.source}</dd>
              </div>
            )}
          </dl>

          <section className={styles.text}>
            {packet.text === null ? (
              <p>The written summary of a live case is shown only on the operator&apos;s screen, because it quotes the victim&apos;s report.</p>
            ) : (
              packet.text.split(/\n\n+/).map((para, i) => <Para key={i} text={para} live={!trace.replay} />)
            )}
            {packet.text !== null && (
              <p className={styles.verify} data-ok={verified(packet.citations_verified) || undefined}>
                {verified(packet.citations_verified)
                  ? plain
                    ? "Every number above was checked against the blockchain."
                    : `Every number above was checked against the trace (${packet.cited.length} cited fields).`
                  : "Citations not verified against the trace."}
              </p>
            )}
          </section>

          {audience === "detective" && <Tables trace={trace} plain={plain} />}
          {!trace.replay && (
            <p className={`${styles.verifyNote} ${styles.screenOnly}`}>Live case: addresses are shortened on screen and printed in full.</p>
          )}

          <footer className={styles.foot}>
            Public blockchain data only. Hound never takes custody of funds and never asks for keys or seed phrases. Send through IC3
            or Chainabuse; do not publish.
          </footer>
        </main>

        <div className={styles.screenOnly}>
          {code ? (
            <NextStep href={`/my/${code}`} label="Back to your case">
              Keep your case code, {code}. It opens your case again.
            </NextStep>
          ) : (
            <NextStep href="/proof" label="See the proof on a real DOJ case">
              Hound ran blind on a real 2024 case and found the wallets the DOJ seized.
            </NextStep>
          )}
        </div>
      </div>
    </>
  );
}

const IS_HEX = /^0x[0-9a-fA-F]{40,64}$/; // no /g: .test() must not carry lastIndex between parts

/** Live cases: short on screen (§0, DEMO.md "never on screen"), full in the printed / PDF copy for the detective. */
function Addr({ v, live }: { v: string; live: boolean }) {
  if (!live) return <>{v}</>;
  return (
    <>
      <span className={styles.screenOnly}>{shortAddr(v)}</span>
      <span className={styles.printOnly}>{v}</span>
    </>
  );
}

/** Writer text, with every address / hash passed through Addr. */
function Rich({ text, live }: { text: string; live: boolean }) {
  if (!live) return <>{text}</>;
  const parts = text.split(/(0x[0-9a-fA-F]{40,64})/g);
  return (
    <>
      {parts.map((p, i) => (IS_HEX.test(p) ? <Addr key={i} v={p} live /> : p))}
    </>
  );
}

function Para({ text, live }: { text: string; live: boolean }) {
  const lines = text.split("\n");
  const items = lines.filter((l) => l.startsWith("- "));
  if (items.length === 0)
    return (
      <p>
        <Rich text={text} live={live} />
      </p>
    );
  const lead = lines.filter((l) => !l.startsWith("- "));
  return (
    <>
      {lead.length > 0 && (
        <p>
          <Rich text={lead.join(" ")} live={live} />
        </p>
      )}
      <ul>
        {items.map((l) => (
          <li key={l}>
            <Rich text={l.slice(2)} live={live} />
          </li>
        ))}
      </ul>
    </>
  );
}

function Tables({ trace, plain }: { trace: Trace; plain: boolean }) {
  const edges = [...trace.edges].sort((a, b) => a.hop - b.hop || b.attributed_amount - a.attributed_amount);
  return (
    <>
      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <h2 className={styles.h2}>Where the money stopped, and who to contact</h2>
          <span className={styles.count}>
            {trace.endpoints.length} {plain ? (trace.endpoints.length === 1 ? "place" : "places") : "endpoints"}
          </span>
        </div>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Address</th>
                <th scope="col">Stop</th>
                <th scope="col" className={styles.num}>Victim money</th>
                <th scope="col">Freeze</th>
                <th scope="col">Contact</th>
              </tr>
            </thead>
            <tbody>
              {trace.endpoints.map((p) => {
                const n = trace.nodes.find((x) => x.address === p.address);
                return (
                  <tr key={p.address}>
                    <td className="mono">
                      <Addr v={p.address} live={!trace.replay} />
                    </td>
                    <td>
                      <span className={styles.tag} data-reason={p.reason}>
                        {p.reason.replaceAll("_", " ")}
                      </span>
                      {p.exchange ? ` (${p.exchange})` : ""}
                    </td>
                    <td className={`mono ${styles.num}`}>{usdt(p.victim_remaining ?? p.victim_inflow)}</td>
                    <td>
                      {n?.frozen?.is_frozen ? (
                        <>
                          <span className={styles.tag} data-reason="frozen">
                            Frozen {n.frozen.frozen_at?.slice(0, 10)}
                          </span>
                          {n.frozen.freeze_tx && (
                            <span className={`mono ${styles.tx}`}>
                              <Addr v={n.frozen.freeze_tx} live={!trace.replay} />
                            </span>
                          )}
                        </>
                      ) : (
                        <span className={styles.tag}>Not frozen</span>
                      )}
                    </td>
                    <td>{REASON_CONTACT[n?.frozen?.is_frozen ? "frozen" : p.reason] ?? "None"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <h2 className={styles.h2}>Every transfer</h2>
          <span className={styles.count}>{edges.length} transfers</span>
        </div>
        <ul className={styles.method}>
          <li>{trace.method.accounting} accounting</li>
          <li>Up to {trace.method.max_hops} hops</li>
          <li>Branches under {trace.method.min_amount} USDT not expanded</li>
          {trace.method.as_of_block ? <li>Chain data cut off at block {trace.method.as_of_block}</li> : null}
        </ul>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Hop</th>
                <th scope="col">From → to</th>
                <th scope="col" className={styles.num}>Victim money</th>
                <th scope="col">Confidence</th>
                <th scope="col">Transactions</th>
              </tr>
            </thead>
            <tbody>
              {edges.map((e) => (
                <tr key={`${e.from}->${e.to}:${e.token}`}>
                  <td>
                    <span className={styles.hop}>{e.hop}</span>
                  </td>
                  <td className="mono">
                    <Addr v={e.from} live={!trace.replay} />
                    <br />→ <Addr v={e.to} live={!trace.replay} />
                  </td>
                  <td className={`mono ${styles.num}`}>{tok(e.attributed_amount, e.token)}</td>
                  <td>
                    {pct(e.confidence)} · {e.method}
                  </td>
                  <td className="mono">
                    {e.tx_hashes.slice(0, TX_SHOWN).map((h) => (
                      <span key={h} className={styles.tx}>
                        <Addr v={h} live={!trace.replay} />
                      </span>
                    ))}
                    {e.tx_hashes.length > TX_SHOWN && <span className={`${styles.tx} ${styles.more}`}>+{e.tx_hashes.length - TX_SHOWN} more in the trace</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

/** The writer reports {verified, total}; older backends sent a boolean. */
// A consolidation hop can carry hundreds of transfers; three per row keeps the packet printable.
const TX_SHOWN = 3;

function verified(c: { verified: number; total: number } | boolean | undefined): boolean {
  if (typeof c === "boolean" || c === undefined) return !!c;
  return c.total > 0 && c.verified === c.total;
}
