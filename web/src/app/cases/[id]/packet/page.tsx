import Link from "next/link";
import { ApiError, Bar } from "@/components/Chrome";
import PrintButton from "@/components/PrintButton";
import { HoundApiError, getPacket, usingFixtures, type Packet } from "@/lib/api";
import { pct, shortAddr, usdt } from "@/lib/format";
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
  const audience = (await searchParams).audience === "victim" ? "victim" : "detective";
  let data: Packet | null;
  try {
    data = await getPacket(id, audience);
  } catch (err) {
    if (!(err instanceof HoundApiError)) throw err;
    return (
      <>
        <Bar offline={usingFixtures} />
        <ApiError message={err.message} />
      </>
    );
  }
  const caseHref = `/cases/${encodeURIComponent(id)}`;
  if (!data) {
    return (
      <>
        <Bar offline={usingFixtures}>Packet</Bar>
        <div className="api-error" role="alert">
          <p className="eyebrow">No finished trace yet</p>
          <p>
            The packet is written from the latest finished trace. <Link href={caseHref}>Run the trace for {id}</Link>, then come back.
          </p>
        </div>
      </>
    );
  }

  const { packet, trace } = data;
  return (
    <>
      <div className={styles.screenOnly}>
        <Bar offline={usingFixtures}>Packet · {id}</Bar>
      </div>
      <main className={styles.sheet}>
        <div className={`${styles.tools} ${styles.screenOnly}`}>
          <Link href={caseHref}>← Back to the trace</Link>
          <span className={styles.toggle} role="group" aria-label="Packet version">
            <Link href="?audience=detective" aria-current={audience === "detective" ? "page" : undefined}>
              For the detective
            </Link>
            <Link href="?audience=victim" aria-current={audience === "victim" ? "page" : undefined}>
              For the victim
            </Link>
          </span>
          <PrintButton />
        </div>

        <header className={styles.head}>
          <div>
            <p className="eyebrow">Hound case packet · {audience === "detective" ? "investigator copy" : "victim copy"}</p>
            <h1>{trace.replay ? "Replay of a historical case" : "Scam funds trace"}</h1>
            <p className={styles.meta}>
              Case <span className="mono">{trace.case_id}</span> · trace <span className="mono">{trace.trace_id}</span> · generated{" "}
              {trace.created_at.slice(0, 10)}
            </p>
          </div>
          <p className={styles.stamp}>Reported, not proven</p>
        </header>

        <section className={styles.text}>
          {packet.text.split(/\n\n+/).map((para, i) => (
            <Para key={i} text={para} live={!trace.replay} />
          ))}
          <p className={styles.verify}>
            {packet.citations_verified
              ? `Every number above was checked against the trace (${packet.cited.length} cited fields).`
              : "Citations not verified against the trace."}
            {packet.source ? ` Written by: ${packet.source}.` : ""}
          </p>
        </section>

        {audience === "detective" && <Tables trace={trace} />}
        {!trace.replay && (
          <p className={`${styles.verify} ${styles.screenOnly}`}>Live case: addresses are shortened on screen and printed in full.</p>
        )}

        <footer className={styles.foot}>
          Public blockchain data only. Hound never takes custody of funds and never asks for keys or seed phrases. Send through IC3
          or Chainabuse; do not publish.
        </footer>
      </main>
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

function Tables({ trace }: { trace: Trace }) {
  const edges = [...trace.edges].sort((a, b) => a.hop - b.hop || b.attributed_amount - a.attributed_amount);
  return (
    <>
      <section>
        <h2 className={styles.h2}>Where the money stopped, and who to contact</h2>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Address</th>
                <th scope="col">Stop</th>
                <th scope="col">Victim money</th>
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
                      {p.reason.replaceAll("_", " ")}
                      {p.exchange ? ` (${p.exchange})` : ""}
                    </td>
                    <td className="mono">{usdt(p.victim_remaining ?? p.victim_inflow)}</td>
                    <td>
                      {n?.frozen?.is_frozen ? (
                        <>
                          Frozen {n.frozen.frozen_at?.slice(0, 10)}
                          {n.frozen.freeze_tx && (
                            <span className="mono">
                              {" "}
                              <Addr v={n.frozen.freeze_tx} live={!trace.replay} />
                            </span>
                          )}
                        </>
                      ) : (
                        "Not frozen"
                      )}
                    </td>
                    <td>{REASON_CONTACT[p.reason] ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
      <section>
        <h2 className={styles.h2}>Every hop</h2>
        <p className={styles.meta}>
          {trace.method.accounting} accounting, up to {trace.method.max_hops} hops, branches under {trace.method.min_amount} USDT not
          expanded{trace.method.as_of_block ? `, chain data cut off at block ${trace.method.as_of_block}` : ""}.
        </p>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Hop</th>
                <th scope="col">From → to</th>
                <th scope="col">Victim money</th>
                <th scope="col">Confidence</th>
                <th scope="col">Transactions</th>
              </tr>
            </thead>
            <tbody>
              {edges.map((e) => (
                <tr key={`${e.from}${e.to}`}>
                  <td>{e.hop}</td>
                  <td className="mono">
                    <Addr v={e.from} live={!trace.replay} />
                    <br />→ <Addr v={e.to} live={!trace.replay} />
                  </td>
                  <td className="mono">{usdt(e.attributed_amount)}</td>
                  <td>
                    {pct(e.confidence)} · {e.method}
                  </td>
                  <td className="mono">
                    {e.tx_hashes.map((h) => (
                      <span key={h} className={styles.tx}>
                        <Addr v={h} live={!trace.replay} />
                      </span>
                    ))}
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
