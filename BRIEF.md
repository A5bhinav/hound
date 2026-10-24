# HOUND: Cal Hacks 13.0 team brief v3 (single source of truth)

**Paste this whole file into your Claude / coding agent.** It contains the problem, the product, the repo layout, the shared data formats, every interface between our parts, and your personal task list. Your agent should read §1 to §8 for context, then do **your section in §9**, building against the interfaces in §8. If your part needs something from someone else that isn't ready, build against the example files and stubs in §8.4 instead of waiting.

Team: Ishaan Pandey (`ish-cs`), Abhinav Jinka (`A5bhinav`), Aaryan Gandhi (`AaryanGG`), CK Duan (`chengkaiduan`). Repo: **github.com/A5bhinav/hound** (public). Last updated Fri Oct 23, 2026, 9:35 PM. **Skeleton is on `main`**: schemas, real-data fixtures, every route running on stubs, tests. v3 = v2 (Jinka's and CK's reviews of v1 folded in) + a full role split with no gaps + interfaces and schemas. The earlier Hound idea (an AP payments agent) is dead; the name stays, the product is new.

---

## 1. One line
Hound takes one scam victim's report, follows the money to where it sits, and finds **everyone else still paying the same scam**, so they can be warned and their next send held before it leaves.
Opening line on stage: **"Americans over 60 lost $4.4 billion to crypto scams last year. We never touch money and never ask for keys."**

## 2. The problem (numbers checked)
- **Size.** FBI IC3 2025: $11.4B in crypto fraud losses (record, up 22%), $7.2B of it crypto investment fraud (pig-butchering: fake romance or friendship, then a fake investment app), **$4.4B lost by people 60+** (all exact in the IC3 PDF). Separately, 12,444 people over 60 lost more than $100K each **to scams of all kinds** (not crypto only: say "to scams").
- **Warning works, recovery mostly doesn't.** The FBI's Operation Level Up has notified 10,406 victims and prevented about $660M in losses cumulatively (FBI, as of Oct 2026; CK checked). Use these numbers, not the older $225M figure.
- **Freezing is real.** Tether can freeze USDT on one verified law-enforcement request, no court order needed. BlockSec counted **4,163 addresses and $1.26B in USDT frozen on Ethereum and Tron in 2025**. Most recent freezes are on Tron (328 of 370 addresses in one 30-day window).
- **The gap.** Victims report to local police, who mostly can't trace crypto. Serious tracing tools are sold to agencies and companies: TRM launched **Co-Case Agent** (Mar 25 2026), an AI that traces fund flows from plain-English prompts, for TRM customers. **Chainabuse** (TRM-owned, free) collects victim reports of scam addresses, has an API, and already lets exchanges check reported addresses.
- **What's new in Hound:** (1) a front door for victims, (2) an action-ready packet, (3) linking victims together, and (4) **spreading the warning beyond reported addresses**: Chainabuse only knows addresses someone reported; Hound follows the money to find the cluster wallets nobody has reported yet. Chainabuse is an input, not a rival.
- Do **not** say "nobody does this". Say: "Tools exist for experts. Hound starts from a scared victim's phone call and produces a filed-ready packet in minutes."

## 3. Where the "save" happens
- A bank never sees the scam wallet: the victim sends dollars to their own exchange account, buys USDT, and sends it out from there. UK refund rules exclude payments to accounts you control, including crypto exchanges. **No bank story, no Nessie.**
- The save happens at the **exchange withdrawal or wallet send screen**. Hound exposes a check API: "is this destination part of a traced scam cluster?" → allow / warn / hold, with evidence.
- "Other payers" are warned through **the exchange they send from**: Hound sees which exchange each other payer's money came out of, and the packet asks that exchange to warn its user. That's how one report becomes prevention.

## 4. The product, end to end
1. **Intake.** The victim calls (Twilio + Cartesia voice) and tells the story: scam app name, platform, dates, amounts, which exchange they sent from. Nobody reads a 64-character hash over the phone, so the agent texts a link; the victim uploads a screenshot of the send screen; Claude reads it and extracts the tx hash and addresses. Output: a **Case** (§8.2).
2. **Chain data.** Ethereum first (Blockscout API, free, no key; our answer-key case is on Ethereum), Tron second (TronGrid). Disk cache for every response, back-off on HTTP 429, **log every empty result** (the kill test got one silent zero that a retry fixed).
3. **Trace engine** (deterministic code, no LLM in the loop). Forward from the victim's send, **FIFO** accounting (the method DOJ used in our case). Confidence and method on every hop. Hard caps: max hops, max branches per node, pagination. Stops at: an exchange (labelled or classified deposit / hot wallet), a wallet still holding USDT (balance + Tether-frozen check), a dead end (mixer, unknown bridge, shown honestly), dust, or max hops. Output: a **Trace** (§8.3).
4. **Claude does exactly two jobs.** (a) **Address classifier**: behaviour features in → kind + reasons + confidence. (b) **Case writer**: plain English for the victim, formal for the detective; it may **only cite fields from the Trace object**, and a test fails the build if any number in the packet isn't in the Trace. Branch triage is code (sort by amount, timing, recency); Claude only explains it.
5. **Other payers + watchlist.** From the scam wallets found, list every other wallet paying in over the last 7 days, how much, and which exchange it came from. Real numbers only: in the DOJ replay, the complaint's 38 victims (say so); in a live case, the on-chain count, called "other wallets paying in", never "victims". **Watchlist rule:** exchange-labelled addresses are never on it; an address needs ≥2 independent reports or a direct scam-wallet hit; low confidence = warn, never hold.
6. **Exchange hold.** A mock exchange withdrawal screen calls the check API and holds the send with evidence.
7. **Packet.** One printable page / PDF: hops, tx hashes, amounts, confidence, freeze status, which exchanges and Tether to contact, an IC3-ready summary. Freeze requests use "address balance ≥ victim's inflow", never a diluted share. Labelled "reported, not proven". Sent via Chainabuse or IC3, never published.
8. **UI.** Trace graph (hops unfold, amounts on edges, confidence, "Tether already froze this" badge, dead ends visible), other-payers view, exchange hold screen, packet page, proof panel.

## 5. Proof (three layers)
1. **DOJ match (answer key, secured).** *United States v. 4,340,000 Tether*, N.D. Ohio **1:25-cv-00386**, filed Feb 27 2025 (CourtListener docket 69684982; PDF in `data/doj/`). 38 victims traced by FIFO into 3 Ethereum USDT wallets. DOJ truncated every address; we recovered the full ones from Tether's public `AddedBlackList` events, and the freeze dates match the complaint:
   | DOJ label | Full address | Frozen |
   |---|---|---|
   | A-7 | 0xa1770ead287dc8e91631a7a323390d5b744f0021 | block 20140818, Jun 21 2024 |
   | A-8 | 0x4e5cda8f0d772ac57e947545192a0657ad47abb5 | block 20170086, Jun 25 2024 |
   | A-9 | 0xafd770d8898a0e323c607fe91358345e7b2378a5 | block 20140808, Jun 21 2024 |
   - **The real path (CK, complaint ¶¶ 69-74):** 11 intermediates: A-1 to A-6, B-1 to B-4, C-1. Funds moved in a "convoluted circular pattern" among A-1 to A-5 (¶ 70), so **the engine must handle cycles**. Everything then **consolidates at A-6** (`0x58e99d9413bb6ce05748a84f76e5fff4bb2d0dcb`, ends b2d0dcb, confirmed) via 4 transfers May 21-30 2024, and A-6 fans out to A-7 / A-8 / A-9. The B branch (B-1 / C-1 → B-2 / B-3 / B-4) also lands at A-6. FIFO through the A-6 consolidation is the real test.
   - **Method wording:** DOJ used FIFO for its 5 named victims; for the other 28 it allowed "LIFO, PIFO, or FIFO" (¶ 81), and LIFO for 5 unidentified accounts (¶ 82). On stage: "FIFO, DOJ's method for its named victims."
   - **Scoreboard metric (CK):** intermediates reached (x/11), A-6 reached, finals reached (x/3), per-wallet totals vs ¶¶ 83-85. Partial credit shown honestly.
   - **Never cite TRM's blog for this case:** it says Tron and cross-chain swaps; the complaint says Ethereum, no bridges.
   - DOJ intermediates already found by a naive script: `0xcf9bbfa762ef5a84ba3d25350de941a6db485027` (A-1, USDT after the victims' swap) → `0x78366b2f6c5321ac30629c078120385ae2da1a06` → `0x9eb0c71e79066552bdd05a69fc4dcac075db5e1f` → A-7 / A-9, all Ethereum USDT, no bridge. Also `0xdf6fa72c71577c3a3209db202d4815021f0ed53f`, `0x07fbb418aac62abc4ca3e7ee8ccf8ce7693e9d53`, and A-6 `0x58e99d9413bb6ce05748a84f76e5fff4bb2d0dcb`. Still missing (prefix…suffix): e79…c2d6ad0, a32…6f4dbb8, 212…4d9c794, 447…eb691, d95…4be2cd4, 28b…fd1.
   - DOJ's per-wallet totals to score against (complaint ¶¶ 83-85): A-7 2,690,294 USDT, A-8 1,765,180 USDT, A-9 795,255 USDT traced from victims.
   - **Holdout rule:** none of these addresses may go into the label DB. Label DB = public exchange labels + OFAC only. Say "blind" on stage and show the holdout list.
   - **Wording:** "reached the same three wallets DOJ seized" (the FBI also had subpoenas). Historical cases are a **replay**, never "sitting there right now".
2. **Freeze backtest.** Every USDT freeze is a public on-chain event. For a sample of frozen addresses, measure how long the money sat there before Tether froze it. "The window" becomes our own measured number.
3. **Weekend scan.** Run Hound on recent public Chainabuse reports and show: "Right now, $X from reported scams sits in N addresses not yet frozen." Labelled "reported, not proven". Sent through Chainabuse / IC3 only.

## 6. The 3-minute demo
- 0:00 "Americans over 60 lost $4.4B to crypto scams last year." "We never touch money or ask for keys."
- 0:20 The call: story by phone, screenshot by text, the case card fills in.
- 0:50 The trace unfolds. **Primary ending:** a fresh case from this month's Chainabuse reports where money still sits in an address (gold, real). **Fallback:** "landed at exchange X deposit address, request ready" (red, real). No synthetic ending.
- 1:20 The twist: N other wallets are paying into the same scam this week (real count; DOJ replay = the complaint's 38 victims).
- 1:45 An exchange withdrawal gets held, with evidence.
- 2:05 The detective's packet: one page.
- 2:25 Proof: the DOJ match (blind, holdout shown), the freeze backtest number, and what we found this weekend.
Judges pick from a **curated case list**. No arbitrary hashes (exchange wallets with millions of transfers stall the demo).

## 7. Repo, stack, and rules for every agent
- **Stack (decided; don't change it without telling Ishaan):** Python 3.12 + FastAPI backend in `backend/`; Next.js + TypeScript + React frontend in `web/`; graph with `react-force-graph` or Cytoscape (Aaryan's choice). Claude via the Anthropic SDK. One shared `.env` (never committed).
- **Layout:**
  ```
  hound/
    schemas/            case.schema.json, trace.schema.json           (Ishaan)
    examples/           ohnd_replay.case.json, ohnd_replay.trace.json (Ishaan, real data)
    backend/hound/
      chain/            eth.py, tron.py, cache.py, labels.py, freezes.py   (Jinka)
      watch/            other_payers.py, watchlist.py, check.py            (Jinka)
      engine/           trace.py, fifo.py                                  (Ishaan)
      llm/              classify.py, writer.py                             (Ishaan)
      proof/            doj_ohnd.py, backtest.py, scan.py, chainabuse.py   (CK)
      intake/           voice.py, screenshot.py                            (CK)
      api.py            FastAPI app, all routes                            (Ishaan wires)
    backend/tests/      one test file per module
    web/                Next.js app                                        (Aaryan)
    data/doj/           complaint PDF + holdout.json (committed)
    data/cases/         curated demo cases (committed)
    cache/              API response cache (gitignored)
  ```
- **Git:** work on your own branch (`pandey`, `jinka`, `cheng`, `gandhi`). Open a PR into `main`; **Ishaan merges**. Merge small and often (at least every 3 hours). Never force-push `main`.
- **Secrets:** the repo is **public**. Never commit `.env`, keys, or `cache/`. Put every new env var in `.env.example` with an empty value.
- **Env vars:** `ANTHROPIC_API_KEY`, `ETHERSCAN_API_KEY` (backup source), `TRONGRID_API_KEY`, `CHAINABUSE_API_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `CARTESIA_API_KEY`, `HOUND_API_URL` (web → backend, default `http://localhost:8000`).
- **Hackathon rule:** all code is written at the event. No pre-written code.
- **Every module fails loudly.** Raise with a useful message; log API errors, retries and empty results. A silent zero in a fraud trace is the worst possible bug.

## 8. Shared contracts (build against these)

### 8.1 Units and naming
- Addresses lowercase for Ethereum, base58 as-is for Tron. Chains: `"ethereum"`, `"tron"`.
- Amounts are **decimal numbers in whole token units** (USDT has 6 decimals on-chain; adapters convert). Times are ISO 8601 UTC strings (`2024-06-21T14:53:11Z`).
- USDT contracts: Ethereum `0xdac17f958d2ee523a2206206994597c13d831ec7`, Tron `TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t`. Freeze event: `AddedBlackList(address)`, Ethereum topic0 `0x42e160154868087d6bfdc0ca23d96a1c1cfa32f1b72ba9ba27b69b98a0d819dc`.

### 8.2 Case (output of intake, input to the engine)
```json
{
  "case_id": "ohnd-replay-001",
  "created_at": "2026-10-24T03:00:00Z",
  "source": "phone | screenshot | chainabuse | doj_replay",
  "victim": { "alias": "Victim A.H.", "age_band": "60+", "exchange_used": "Coinbase" },
  "story": { "scam_app": "string", "platform": "WhatsApp", "first_contact": "2024-02-01", "summary": "string" },
  "sends": [
    { "chain": "ethereum", "tx_hash": "0x...", "from": "0x...", "to": "0x...",
      "token": "USDT", "amount": 195859.0, "time": "2024-05-02T10:00:00Z" }
  ],
  "status": "intake | tracing | traced | packet_ready"
}
```
No phone numbers or real names in committed files.

### 8.3 Trace (output of the engine, input to the UI, packet, watchlist and proof)
```json
{
  "trace_id": "string", "case_id": "string", "created_at": "ISO",
  "method": { "accounting": "FIFO", "max_hops": 8, "max_branches_per_node": 12, "min_amount": 100 },
  "nodes": [
    { "address": "0x...", "chain": "ethereum",
      "kind": "victim | intermediate | exchange_deposit | exchange_hot | holding | mixer | bridge | unknown",
      "label": "Binance 14 | null", "label_source": "exchange_list | ofac | classifier | null",
      "classifier": { "kind": "string", "confidence": 0.8, "reasons": ["string"] },
      "balance_usdt": 0.0,
      "frozen": { "is_frozen": true, "frozen_at": "ISO", "freeze_tx": "0x..." },
      "depth": 0 }
  ],
  "edges": [
    { "from": "0x...", "to": "0x...", "token": "USDT",
      "amount": 1638562.58, "attributed_amount": 195859.0,
      "tx_hashes": ["0x..."], "first_time": "ISO", "last_time": "ISO",
      "hop": 1, "confidence": 0.9, "method": "direct | peel | consolidation | swap | bridge_match" }
  ],
  "endpoints": [
    { "address": "0x...", "reason": "exchange | holding | frozen | dead_end | dust | max_hops",
      "victim_inflow": 195859.0, "balance_usdt": 0.0, "freezable": false, "exchange": "string | null" }
  ],
  "other_payers": [
    { "address": "0x...", "amount": 0.0, "window_days": 7, "source_exchange": "string | null", "confidence": 0.7 }
  ],
  "stats": { "api_calls": 0, "cache_hits": 0, "empty_results": 0, "elapsed_ms": 0 },
  "audit_log": [ { "t": "ISO", "step": "fetch | cache_hit | empty_result | hop | skip_branch | cap_hit | stop | classify | freeze_check | error", "address": "0x... | null", "detail": "string" } ]
}
```
`audit_log` is the Hyphenate "clean record of its work": every step in order, including skipped branches and caps hit. Edges are aggregated per (from, to) pair; `tx_hashes` lists every underlying transfer. `other_payers` is filled by Jinka's `other_payers()` after the engine runs.

### 8.4 Python interfaces (function names are fixed; internals are yours)
```python
# backend/hound/chain/  (Jinka)
get_transfers(chain, address, token=None, before=None, after=None) -> list[Transfer]
    # Transfer = {"chain","tx_hash","from","to","token","amount","time","block"}; both directions; paginated; cached
get_balance(chain, address, token="USDT") -> float
freeze_status(chain, address) -> {"is_frozen": bool, "frozen_at": str|None, "freeze_tx": str|None}
freeze_events(chain, after, before) -> list[{"address","frozen_at","freeze_tx","block"}]
label(chain, address) -> {"name": str, "kind": "exchange_hot|exchange_deposit|ofac|service", "source": str} | None

# backend/hound/watch/  (Jinka)
other_payers(trace, window_days=7) -> list[OtherPayer]
check(chain, address) -> {"decision": "allow|warn|hold", "reasons": [str], "evidence": {...}, "confidence": float}

# backend/hound/engine/  (Ishaan)
run_trace(case) -> Trace

# backend/hound/llm/  (Ishaan)
classify(features: dict) -> {"kind": str, "confidence": float, "reasons": [str]}
write_case(trace, case, audience="victim|detective") -> {"text": str, "cited": [str]}

# backend/hound/proof/  (CK)
chainabuse_reports(chain=None, since=None) -> list[{"address","chain","category","reported_at","report_count","confidence"}]
doj_scoreboard() -> {"case": "1:25-cv-00386", "targets": [...], "reached": [...], "totals_vs_doj": [...], "holdout": [...]}
freeze_backtest(sample=200) -> {"median_hours_before_freeze": float, "p90_hours": float, "n": int, "method": str}
weekend_scan() -> {"addresses": int, "usdt_unfrozen": float, "cases": [...]}

# backend/hound/intake/  (CK)
case_from_screenshot(image_bytes, story: dict) -> Case
# voice: Twilio webhook routes registered in api.py; produces a story dict, sends the SMS upload link
```
Until a dependency exists, stub it with the matching object from `examples/` (e.g. `run_trace` returns `examples/ohnd_replay.trace.json`). Replace the stub when the real one is merged.

### 8.5 HTTP API (FastAPI, `backend/hound/api.py`, port 8000)
| Method + route | Returns | Owner of the logic |
|---|---|---|
| `GET /cases` | curated demo case list | Ishaan |
| `POST /cases` (Case body) | Case with `case_id` | Ishaan |
| `POST /cases/{id}/trace` | Trace | Ishaan (engine) + Jinka (other payers) |
| `GET /traces/{id}` | Trace | Ishaan |
| `GET /cases/{id}/packet?audience=detective` | `{text, cited}` + the Trace, for the packet page | Ishaan (writer) |
| `GET /check?chain=&address=` | check() result | Jinka |
| `GET /proof/scoreboard` | doj_scoreboard() | CK |
| `GET /proof/backtest` | freeze_backtest() | CK |
| `GET /scan/latest` | weekend_scan() | CK |
| `POST /intake/screenshot` (multipart) | Case | CK |
| `POST /voice/*` | Twilio webhooks | CK |

## 9. Roles and task lists
Your agent works through your list top to bottom. **"Done"** means merged into `main` via PR, with a test or script that proves it works on the real DOJ case.

### 9.1 Ishaan: integrator, engine, Claude, pitch
1. **Tonight:** push `schemas/`, `examples/ohnd_replay.case.json` + `ohnd_replay.trace.json` (real DOJ addresses and tx hashes), `.gitignore`, `.env.example`, the backend skeleton (`backend/hound/` packages + `api.py` with stub routes), and this brief as `BRIEF.md`, so everyone can start.
2. Trace engine: FIFO, **cycle handling** (A-1 to A-5 circulate funds), FIFO through the **A-6 consolidation**, stop rules, caps, confidence + method per hop, deterministic branch triage. Done = starting from DOJ A-1 (`0xcf9…485027`) it reaches A-7 / A-9 blind (holdout respected).
3. `classify()` with Claude (features → kind + reasons), cached per address.
4. `write_case()` + the **citation test**: every number in the text must appear in the Trace.
5. Wire every route in §8.5; merge PRs; keep `main` running end to end by **Sat 12 PM**.
6. Pitch: 2-minute and 3-minute versions + Q&A prep (PRESSURE_TEST.md and both reviews).

### 9.2 Jinka: chain data, labels, freezes, watchlist, check API
1. **Tonight:** get `ETHERSCAN_API_KEY` and `TRONGRID_API_KEY`.
2. `chain/eth.py`: `get_transfers` via Blockscout (`https://eth.blockscout.com/api?module=account&action=tokentx|txlist&...`), Etherscan as fallback. Pagination (`page`, `offset=1000`), 429 back-off, retries. Log empty results.
3. `chain/cache.py`: disk cache in `cache/` keyed by (chain, address, params). Pre-warm every address on the DOJ path and in the demo cases.
4. `chain/freezes.py` (**CK's backtest is blocked on this, do it early**): `freeze_status` + `freeze_events` from `AddedBlackList` logs (Blockscout `module=logs&action=getLogs&topic0=...`). Done = returns the 3 DOJ freezes with the blocks in §5.
5. `chain/labels.py`: **seed Ethereum exchange hot wallets first** (Binance, Coinbase, OKX, Kraken, Crypto.com, KuCoin, Bybit) or the other-payers "source exchange" view is empty; then OFAC. Exchange hot-wallet labels from public lists (e.g. community Etherscan label datasets on GitHub; check the licence) + OFAC SDN digital-currency addresses (treasury.gov SDN list). **Never add any address in `data/doj/holdout.json`**; a test enforces it.
6. `get_balance`.
7. `chain/tron.py`: the same interface via TronGrid (Should tier, after Ethereum works).
8. `watch/other_payers.py`: senders into the trace's scam wallets in the last N days, amounts, source exchange (look one hop back for an exchange label).
9. `watch/watchlist.py` + `check.py`: the rules in §4.5. Done = `check()` on A-7 returns hold with evidence; on a Binance hot wallet it returns allow.
10. **x402 (Should, also wins the Coinbase track):** pay-per-call middleware on `GET /check`.

### 9.3 CK: proof, Chainabuse, intake, fact-checking
1. **Tonight:** get `CHAINABUSE_API_KEY`, a Twilio trial (verify your phone) and a Cartesia key. **Find the demo's gold ending**: a fresh case from this month's Chainabuse reports (USDT, Ethereum preferred, Tron OK) where reported money is still sitting unfrozen. Save it to `data/cases/`. If none by Sat 10 AM, tell Ishaan; fallback = "landed at exchange X".
2. Verify the Level Up numbers in §2 and any number anyone wants to say on stage. Keep `data/facts.md` with each number and its source link.
3. `data/doj/holdout.json`: every address in the complaint (full where we have it, prefix…suffix where not) + DOJ's per-wallet totals.
4. `proof/doj_ohnd.py` → `doj_scoreboard()`: run the engine from the victims' first USDT addresses and compare endpoints and per-wallet totals with DOJ ¶¶ 83-85.
5. `proof/backtest.py` → `freeze_backtest()`. Definition: **median hours from first USDT inflow to the AddedBlackList event, over N frozen Ethereum addresses in 2025.** On-screen caveat: it only measures addresses Tether did freeze.
6. **Apify actor (Should, also wins the Apify track):** scrape public scam-victim posts for tx hashes / addresses into `data/cases/` candidates, so the gold-case hunt doesn't burn the Chainabuse quota.
7. `proof/chainabuse.py` + `proof/scan.py` → `weekend_scan()`. **Budget: the free Chainabuse key is 10 calls/month × 50 reports ≈ 500 reports for the whole weekend.** Cache every response; CK applied for partner tier (don't count on it).
8. **Sat afternoon (Should tier):** `intake/` voice line (Twilio number → Cartesia voice agent collects the story → SMS upload link) and `case_from_screenshot` (Claude vision extracts the tx hash + addresses from a send-screen screenshot).

### 9.4 Aaryan: UI, packet page, video, Devpost
1. **Tonight:** `web/` Next.js scaffold reading `HOUND_API_URL`. Build against `examples/ohnd_replay.trace.json` until the API is live.
2. Trace graph: hops unfold in order, amounts on edges, colour by `kind` (red = exchange, gold = holding + freezable, grey = dead end, frozen badge), confidence visible, click a node for details.
3. Case card (fills in live during intake) + the curated case picker.
4. Other-payers view.
5. Exchange hold screen: a mock exchange withdrawal form that calls `GET /check` and shows allow / warn / hold with evidence.
6. Packet page: printable (browser print to PDF is fine), from `GET /cases/{id}/packet`.
7. Proof panel: scoreboard, backtest number, weekend scan.
8. Demo video (opens with the moment) Sat night; Devpost page draft by Sat 11:30 PM (image, repo link, video, all 4 teammates, every track ticked).

## 10. Timeline and tiers
- **Tonight (Fri):** keys; Ishaan pushes schemas + examples + skeleton; everyone starts on their list against the examples; CK hunts the gold case.
- **By Sat 12 PM (Must):** Ethereum adapter + cache → engine reaches the DOJ wallets blind → graph renders a real Trace → packet page. `main` runs end to end (ugly is fine).
- **By Sat 6 PM:** other payers, watchlist + exchange hold, backtest number, scoreboard.
- **Should:** voice + screenshot intake, weekend scan, Tron adapter.
- **Last:** Ethereum-to-Tron hop, more cases.
- Feature freeze **Sat 10 PM**. Video Sat night. Devpost draft **Sat 11:30 PM**. Bug bash + 5 pitch rehearsals Sun 6-8:30 AM. **Hard deadline Sun 9:00 AM** (at the venue by 8). Judging Sun 10:30 AM-12:30 PM, **all four present** or we're not judged.

## 11. Prize stack (from the official hacker guide)
**Tier 1: Hound fits as designed. Showcase it in the pitch, README and Devpost; no extra build.**
| Track | Prize | How Hound wins it |
|---|---|---|
| **Hyphenate: Autonomous Systems for Finance** | **$8K / $5K / $3K + expedited interviews (top 5)** | Their 4 questions: **Real enough?** Blind against a real DOJ case, real chain data. **Would you hire it?** Seat = *exchange fraud / AML investigator*: read-only access, can't move money, cites every hop (`audit_log`), warns instead of holding when unsure. **Something new?** Tracing that starts from the victim and spreads the warning beyond reported addresses. **The moment:** recovering the addresses DOJ redacted, then reaching DOJ's seized wallets blind. They want: a demo video that **opens with the moment**, a live demo where **they may try their own scenario** (the engine must return a partial trace with honest dead ends, never crash), one line on the seat, and what's real vs simulated. |
| Microsoft "Built for the Real World" | Surface laptop each + FDE tech talk | Customer understanding (victims, exchanges), measurable usefulness (scoreboard + backtest numbers), path to production (exchange check API), responsible design (§12), end to end |
| Cartesia | Meta glasses (TBD) | Voice is the front door for people who can't use a crypto app. 25% of judging is accessibility + responsible use. README must list the Cartesia features used and known limitations |
| Armadin Best Security Hack | TBD (criteria "coming soon") | Fraud tracing + exchange hold |
| Overall / Most Technically Complex / **Best People-First** / Hacker's Choice | MacBook / keyboard / Apple Watch / mouse | Core build |

**Tier 2: cheap adds, each does real work (Should tier, after the Must tier works)**
| Track | Prize | Integration | Owner |
|---|---|---|---|
| **Apify** | $2K / $1K / $800 / $400 / $400 + $400 Best Actor | An Apify actor that scrapes public scam-victim posts (e.g. r/Scams) for tx hashes and addresses. Feeds the gold-case hunt and the weekend scan, and saves the Chainabuse quota (~500 reports all weekend) | CK |
| **Coinbase x402** | $500 USDC per member ($2K) | Pay-per-call on `GET /check` so any wallet or AI agent pays a fraction of a cent to check an address before sending. This is the business model, not a bolt-on | Jinka, after `check()` works |
| CRS: Identity / Fraud Innovation (+ Best Financial AI Agent $500) | FDE interview each | On a warn at the exchange hold, check the customer's CRS **sandbox test identity** for vulnerability signals (60+, sudden large liquidation) and upgrade warn → hold | Optional, Sat evening if on schedule |

Skipped: Nessie, Elastic, Fetch.ai, Factory Droid, Meta, Visa, CREAO, Convex, Moss, SpaceXAI, Bitdeer, Figma, Notability. Ask #0-ask-directors whether there's a cap on tracks per project.

## 12. Honesty rules (shown on screen, enforced in code)
- Confidence on every hop, every dead end visible, "Tether already froze this" badge.
- Public blockchain data only. Findings go to Chainabuse / IC3 / exchanges, never published, labelled "reported, not proven".
- Never takes money, never asks for seed phrases or keys.
- Exchange wallets are never on the watchlist; low confidence = warn, never hold.
- The case writer cites only Trace fields.

Sources: The Block (FBI IC3 2025: theblock.co/post/397134); BlockSec 2025 USDT freeze report (blocksec.com/blog/1-26-billion-frozen-usdt-blacklisting-on-ethereum-and-tron-in-2025); TRM Co-Case Agent (trmlabs.com/resources/blog/trm-labs-launches-co-case-agent-an-ai-assistant-for-every-crypto-investigation); Chainabuse API docs (docs.trmlabs.com/guides/chainabuse/welcome-to-chainabuse-api); PSR APP reimbursement exclusions (A&O Shearman); CourtListener docket 69684982.
