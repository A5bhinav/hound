# Devpost draft (paste into the Devpost fields; Aaryan owns final edits)

**Name:** Hound
**Tagline:** The 911 call for crypto scam victims: follow the money to where it can still be frozen, and stop the next victim's send.

## Inspiration
Americans over 60 lost $4.4 billion to crypto scams in 2025, out of $11.4 billion in crypto fraud losses reported to the FBI. Most of it was pig-butchering: a fake friendship or romance, then a fake investment app. Tracing tools exist, but they are sold to agencies and exchanges. The victim calls local police, who usually can't trace crypto, while Tether can freeze stolen USDT on a single law-enforcement request. We wanted to connect the victim to that request, and use one report to protect the next person.

## What it does
- **Report.** A victim calls the Hound line (Cartesia voice agent) or reports online at houndhelp.vercel.app, then sends a screenshot of their payment. Hound checks it on the live chain, so a made-up payment is rejected. Nobody is asked to read a 64-character hash aloud.
- **Their case.** With their case code, the victim sees where the money went, who can freeze it, a step-by-step "what to do now" (IC3, their exchange, a police freeze request, beware recovery scams), and their own police report.
- **Trace.** Hound follows the stolen money hop by hop with first-in-first-out accounting, through swaps, laundering loops and consolidation wallets, to where it sits: an exchange, a holding wallet, or a wallet Tether already froze. Every hop has a confidence, and every dead end is shown.
- **Warn.** Every wallet in the traced cluster feeds a watchlist. At an exchange withdrawal screen, Hound's check API returns allow, warn or hold, with evidence. Exchanges, routers and bridges are never on the list, and reports alone never cause a hold.
- **Packet.** One page for a detective: every hop with its transaction count and confidence, every endpoint with its freeze status, who to contact (Tether, the exchange, IC3), and a banner naming any branch the trace could not finish, labelled "reported, not proven".

## Try it
- Call **(501) 443-1471**, or open **https://houndhelp.vercel.app** and choose **Report online**.
- Play the victim from the DOJ case: save https://houndhelp.vercel.app/demo/receipt.png (A.H.'s real 33 ETH payment) and upload it. Hound finds 101,352 USDT of it, all in wallets Tether froze.
- The judge tour: https://houndhelp.vercel.app/how

## Proof: a real DOJ case, run blind
We replay *United States v. 4,340,000 Tether* (N.D. Ohio 1:25-cv-00386, Feb 2025). The complaint printed every wallet truncated; we recovered all of them from public chain data and Tether's freeze events. The engine starts from one victim's six real ETH sends and gets nothing else: the other 11 DOJ addresses are a holdout (our test suite fails if one appears in engine code), and Tether's freezes are hidden until after the run.

Result: Hound reaches **all 8 intermediate wallets** the DOJ named that it was not given and **all 3 seized wallets**. Against the DOJ's own per-wallet numbers for that victim: **A-7 +0.9%, A-8 +1.04%, A-9 +10.8%**. Every one of the victim's dollars is accounted for. Then we reveal it: Tether froze those wallets 16 to 20 days after she reported to the FBI.

Two more measurements: across 192 of the 657 Ethereum USDT addresses Tether froze in 2025, the median time from the first USDT arriving to the freeze was 45 days. And this weekend we checked 963 reported scam addresses on chain: 14 still hold 91,218 USDT that has not been frozen.

## How we built it
- **Engine (Python):** a deterministic FIFO replay in integer base units, ordered by block and log index; same-transaction ETH-to-USDT swap joins; cycle handling; visible caps (dust, branch limits, call budget, deadline); a full audit log. No LLM ever decides a stop or a hold.
- **Chain data:** Ethereum and Tron adapters (public RPC logs, Blockscout, Etherscan, TronGrid) behind one interface, with a disk cache, record and readonly modes, and a committed snapshot so the DOJ replay runs with zero network calls. Labels from public exchange datasets, OFAC, and an infrastructure allowlist.
- **Claude (Anthropic):** two jobs only. It rewords each wallet's rule-based explanation in plain English, and it drafts the victim and detective summaries using placeholders, never raw numbers. A validator checks every generation and rejects uncited numbers, recovery promises, unknown links and accusations next to addresses, falling back to a fixed template.
- **API:** FastAPI with background trace jobs and live polling. **Web:** Next.js on Vercel, with a money-flow graph (ribbon width = victim money) that unfolds transfer by transfer.
- **Data:** Google BigQuery public Ethereum datasets, Tether `AddedBlackList` events, Chainabuse reports.

## Challenges
- The DOJ truncates addresses (`0xa17 ... 44f0021`), and address-poisoning lookalikes on chain match those truncations. We resolved them by amount and date, ignoring zero-value transfers.
- Our own first engine silently lost money when a laundering loop sent funds back into wallets it had already visited. Adversarial review caught it, and conservation is now tested to the micro-unit.
- Rate limits: free chain APIs returned errors as HTTP 200, which a naive cache would store as a permanent "no transactions". The adapters classify responses and never cache an error.

## What's real vs simulated
Real: the DOJ case, every address and transaction, the swaps, Tether's freezes, the live scam report data. Replayed: the 2024 timing of the DOJ case (labelled REPLAY on screen). Simulated: the exchange withdrawal screen, and the "Play a sample call" button, which replays the report steps from the curated case when no live call is running.

## What's next
Exchange and wallet integrations of the check API, a filing path to Tether and IC3, and a shared watchlist that gets stronger with every free victim report.

## Built with
python, fastapi, next.js, typescript, anthropic-claude, cartesia, google-bigquery, ethereum, tron, usdt

## Tracks
Overall · Most Technically Advanced · Best People-First Social Impact · Hacker's Choice · Hyphenate (Autonomous Systems for Finance; seat: exchange fraud / AML investigator) · Microsoft Built for the Real World + Customer Impact Award · Claude for Public Benefit (Anthropic) · Cartesia · Armadin Best Security Hack

(Use the exact prize names from the Cal Hacks 13.0 Devpost page; the four above in their exact form were checked by Jinka's research.)

Sources for every number: PITCH.md and BRIEF.md §2.

## Gallery
Screenshots from the live site (houndhelp.vercel.app, DOJ replay on the real backend) in `docs/devpost/`, captions as claims:
1. `1-home.png`: "Built for the victim first: call or report online, and Hound never asks for money or keys."
2. `2-trace-reveal.png`: "From one victim's report, blind, Hound reached all 3 wallets the DOJ seized. Tether froze them 16 to 20 days later."
3. `3-exchange-held.png`: "A withdrawal to a wallet from the DOJ case is held, with the evidence."
4. `4-police-report.png`: "One page a detective can act on. Claude writes it, and it can only cite numbers that are in the trace."
5. `5-proof.png`: "Scored blind against the DOJ's own numbers: 8 of 8 wallets in between, 3 of 3 seized."
6. `6-victim-case-phone.png`: "The victim's own case: the payment from her screenshot, where the money is now, each wallet verifiable on Etherscan."
