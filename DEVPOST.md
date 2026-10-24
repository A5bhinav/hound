# Devpost draft (paste into the Devpost fields; Aaryan owns final edits)

**Name:** Hound
**Tagline:** The 911 call for crypto scam victims: follow the money to where it can still be frozen, and stop the next victim's send.

## Inspiration
Americans over 60 lost $4.4 billion to crypto scams in 2025, out of $11.4 billion in crypto fraud losses reported to the FBI. Most of it was pig-butchering: a fake friendship or romance, then a fake investment app. Tracing tools exist, but they are sold to agencies and exchanges. The victim calls local police, who usually can't trace crypto, while Tether can freeze stolen USDT on a single law-enforcement request. We wanted to connect the victim to that request, and use one report to protect the next person.

## What it does
- **Intake.** A victim tells their story by phone (Cartesia voice agent) and uploads a screenshot of their send. Nobody is asked to read a 64-character hash aloud.
- **Trace.** Hound follows the stolen money hop by hop with first-in-first-out accounting, through swaps, laundering loops and consolidation wallets, to where it sits: an exchange, a holding wallet, or a wallet Tether already froze. Every hop has a confidence, and every dead end is shown.
- **Warn.** Every wallet in the traced cluster feeds a watchlist. At an exchange withdrawal screen, Hound's check API returns allow, warn or hold, with evidence. Exchanges, routers and bridges are never on the list, and reports alone never cause a hold.
- **Packet.** One page for a detective: every hop with its transaction count and confidence, every endpoint with its freeze status, who to contact (Tether, the exchange, IC3), and a banner naming any branch the trace could not finish, labelled "reported, not proven".

## Proof: a real DOJ case, run blind
We replay *United States v. 4,340,000 Tether* (N.D. Ohio 1:25-cv-00386, Feb 2025). The complaint printed every wallet truncated; we recovered all of them from public chain data and Tether's freeze events. The engine starts from one victim's six real ETH sends and gets nothing else: the other 11 DOJ addresses are a holdout (our test suite fails if one appears in engine code), and Tether's freezes are hidden until after the run.

Result: Hound reaches **all 8 intermediate wallets** the DOJ named that it was not given and **all 3 seized wallets**. Against the DOJ's own per-wallet numbers for that victim: **A-7 +0.9%, A-8 +1.04%, A-9 +10.8%**. Every one of the victim's dollars is accounted for. Then we reveal it: Tether froze those wallets 16 to 20 days after she reported to the FBI.

## How we built it
- **Engine (Python):** a deterministic FIFO replay in integer base units, ordered by block and log index; same-transaction ETH-to-USDT swap joins; cycle handling; visible caps (dust, branch limits, call budget, deadline); a full audit log. No LLM ever decides a stop or a hold.
- **Chain data:** Ethereum and Tron adapters (public RPC logs, Blockscout, Etherscan, TronGrid) behind one interface, with a disk cache, record and readonly modes, and a committed snapshot so the DOJ replay runs with zero network calls. Labels from public exchange datasets, OFAC, and an infrastructure allowlist.
- **Claude (Anthropic):** two jobs only. It rewords each wallet's rule-based explanation in plain English, and it drafts the victim and detective summaries using placeholders, never raw numbers. A validator checks every generation and rejects uncited numbers, recovery promises, unknown links and accusations next to addresses, falling back to a fixed template.
- **API:** FastAPI with background trace jobs and live polling. **Web:** Next.js with a Cytoscape trace graph that unfolds hop by hop.
- **Data:** Google BigQuery public Ethereum datasets, Tether `AddedBlackList` events, Chainabuse reports.

## Challenges
- The DOJ truncates addresses (`0xa17 ... 44f0021`), and address-poisoning lookalikes on chain match those truncations. We resolved them by amount and date, ignoring zero-value transfers.
- Our own first engine silently lost money when a laundering loop sent funds back into wallets it had already visited. Adversarial review caught it, and conservation is now tested to the micro-unit.
- Rate limits: free chain APIs returned errors as HTTP 200, which a naive cache would store as a permanent "no transactions". The adapters classify responses and never cache an error.

## What's real vs simulated
Real: the DOJ case, every address and transaction, the swaps, Tether's freezes, the live scam report data. Replayed: the 2024 timing of the DOJ case (labelled REPLAY on screen). Simulated: the exchange withdrawal screen.

## What's next
Exchange and wallet integrations of the check API, a filing path to Tether and IC3, and a shared watchlist that gets stronger with every free victim report.

## Built with
python, fastapi, next.js, typescript, cytoscape, anthropic-claude, cartesia, google-bigquery, ethereum, tron, usdt

## Tracks
Overall · Most Technically Complex Hack · Best People-First Hack · Hacker's Choice · Hyphenate (Autonomous Systems for Finance; seat: exchange fraud / AML investigator) · Microsoft Built for the Real World + Customer Impact Award · Anthropic · Cartesia (if voice ships) · Armadin Best Security Hack · Apify (if the scraper ships)

Sources for every number: PITCH.md and BRIEF.md §2.
