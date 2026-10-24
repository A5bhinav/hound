import { HoundMark } from "./Chrome";
import styles from "./HeroMockup.module.css";
import Tilt from "./Tilt";

/** The product, drawn small and tilted beside the hero: a case, its money trail, and where the money reached.
 *  Taken from a real Chainabuse report this month (one victim, two payments: Coinbase on Oct 8, Binance on Oct 15),
 *  with the victim's wallet shortened as on every public page. Illustration only: no live data is fetched. */
export default function HeroMockup() {
  return (
    <div className={styles.stage} aria-hidden="true">
      <Tilt className={styles.card}>
        <aside className={styles.side}>
          <div className={styles.brand}>
            <HoundMark className={styles.mark} />
            Hound
          </div>
          <ul className={styles.menu}>
            <li data-on>
              <Icon d="M4 5h12M4 10h12M4 15h8" /> Case overview
            </li>
            <li>
              <Icon d="M5 5l5 5m0 0l5-5m-5 5v6" /> Transaction graph
            </li>
            <li>
              <Icon d="M3 8l7-4 7 4M5 8v7m10-7v7M3 16h14" /> Exchanges
            </li>
            <li>
              <Icon d="M6 3h6l3 3v11H6zM9 9h4M9 12h4" /> Report
            </li>
            <li>
              <Icon d="M5 6l2 2 4-4M5 12l2 2 4-4M13 7h3M13 13h3" /> What to do
            </li>
          </ul>
        </aside>
        <div className={styles.main}>
          <div className={styles.head}>
            <div>
              <p className={styles.case}>Case MC-1021</p>
              <p className={styles.date}>Reported Oct 21, 2026</p>
            </div>
            <span className={styles.download}>
              <Icon d="M10 4v8m0 0l-3-3m3 3l3-3M5 15h10" /> Download report
            </span>
          </div>
          <div className={styles.body}>
            <svg className={styles.graph} viewBox="0 25 395 220">
              <defs>
                <radialGradient id="hm-glow">
                  <stop offset="0" stopColor="#e5484d" stopOpacity="0.55" />
                  <stop offset="1" stopColor="#e5484d" stopOpacity="0" />
                </radialGradient>
                <marker id="hm-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
                  <path d="M0 0L8 4L0 8" fill="none" stroke="#9a9a9a" strokeWidth="1.2" />
                </marker>
                <marker id="hm-arrow-red" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
                  <path d="M0 0L8 4L0 8" fill="none" stroke="#e5484d" strokeWidth="1.2" />
                </marker>
              </defs>
              <circle cx="40" cy="130" r="40" fill="url(#hm-glow)" />
              <circle cx="40" cy="130" r="20" fill="#c0181f" stroke="#ff5a5f" strokeWidth="1.5" />
              <path d="M60 130 H138" stroke="#e5484d" strokeWidth="1.6" markerEnd="url(#hm-arrow-red)" />
              <g fill="#2a2a2e" stroke="#6a6a70" strokeWidth="1.4">
                <circle cx="152" cy="130" r="13" />
                <circle cx="268" cy="80" r="15" />
                <circle cx="236" cy="172" r="13" />
                <circle cx="372" cy="222" r="13" />
              </g>
              <g fill="none" stroke="#8a8a90" strokeWidth="1.3">
                <path d="M162 124 C190 100 205 82 252 80" markerEnd="url(#hm-arrow)" />
                <path d="M162 136 C182 150 200 166 222 170" markerEnd="url(#hm-arrow)" />
                <path d="M280 74 C300 56 318 44 356 44" markerEnd="url(#hm-arrow)" />
                <path d="M280 88 C302 112 320 126 356 128" markerEnd="url(#hm-arrow)" />
                <path d="M248 176 C290 182 320 190 358 216" markerEnd="url(#hm-arrow)" />
              </g>
              <text x="40" y="172" textAnchor="middle" className={styles.walletT}>
                Your wallet
              </text>
              <text x="40" y="188" textAnchor="middle" className={styles.walletA}>
                0x308d…0f88
              </text>
            </svg>
            <ul className={styles.alerts}>
              <li>
                <span className={styles.logo}>
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <g fill="#F3BA2F" transform="rotate(45 12 12)">
                      <rect x="9.6" y="9.6" width="4.8" height="4.8" />
                      <rect x="9.9" y="2.6" width="4.2" height="4.2" />
                      <rect x="9.9" y="17.2" width="4.2" height="4.2" />
                      <rect x="2.6" y="9.9" width="4.2" height="4.2" />
                      <rect x="17.2" y="9.9" width="4.2" height="4.2" />
                    </g>
                  </svg>
                </span>
                <span>
                  <b>Binance</b>
                  <small>0x28c6…1d60</small>
                </span>
                <em className={styles.alerted}>Alerted</em>
              </li>
              <li>
                <span className={styles.logo}>
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <circle cx="12" cy="12" r="10" fill="#1652F0" />
                    <path d="M15.8 14.6a4.4 4.4 0 1 1 0-5.2" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" />
                  </svg>
                </span>
                <span>
                  <b>Coinbase</b>
                  <small>0x2f1c…8fa4</small>
                </span>
                <em>Under review</em>
              </li>
              <li>
                <span className={styles.logo}>
                  <Icon d="M3 8l7-4 7 4M5 8v7m3.3-7v7m3.4-7v7M15 8v7M3 16h14" />
                </span>
                <span>
                  <b>Unknown</b>
                  <small>0x0796…0000</small>
                </span>
                <em>Traced</em>
              </li>
            </ul>
          </div>
        </div>
      </Tilt>
    </div>
  );
}

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  );
}
