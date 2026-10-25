# Devpost: paste-ready (one section per Devpost field)

Every number here is checked against the code and data (sources: PITCH.md, BRIEF.md §2, data/proof/). Keep the wording simple; if you change a number, check it first.

---

## Project name
Hound

## Elevator pitch (Devpost limit: 200 characters)
The 911 call for crypto scam victims. Hound follows stolen crypto to where it can still be frozen, warns exchanges before the next victim pays, and writes the police report.

---

## About the project

### Inspiration: the problem, simply
Americans over 60 lost **$4.4 billion** to crypto scams last year (FBI IC3, 2025). The usual story: someone builds a fake friendship online, then talks the victim into a fake investment app, and the money vanishes into crypto.

The victim calls the police, who usually can't trace crypto. The tools that *can* trace it are sold to governments and exchanges, not to victims. Yet the money often still sits in a wallet that **Tether can freeze with one law-enforcement request**. The gap isn't the technology; it's that nobody turns the victim's report into that request in time. Across the wallets Tether froze in 2025, the typical wait was **45 days**.

Hound closes that gap: it takes the victim's call, finds the money, tells them who can freeze it, and warns exchanges so the next victim's payment is stopped.

### What it does
1. **Report.** A victim calls our phone line (a voice agent built on Cartesia) or reports online. They tell their story in their own words and send one screenshot of their payment. Nobody has to read a long transaction code out loud.
2. **Follow the money.** Hound reads the screenshot, finds the payment on the blockchain, and follows the money wallet by wallet to where it ended up: an exchange, a wallet that can still be frozen, or a wallet Tether already froze.
3. **Stop the next victim.** Every wallet in the trail goes on a warning list. When someone tries to send money from an exchange to one of those wallets, the exchange can check Hound first and hold the payment, with the evidence attached.
4. **Police report.** Hound writes a one-page report for the detective and a plain-language copy for the victim: every transfer, where the money is now, and who to contact (Tether, the exchange, the FBI's IC3).

The victim gets a case code. With it they can come back any time to see what we found, what to do next, and their report. Every payment and wallet links to Etherscan, so they can check it themselves.

### Results at a glance
| What we measured | Result |
|---|---|
| Wallets the DOJ seized, found blind from one victim's report | **3 of 3** |
| Wallets the FBI named in between, found blind | **8 of 8** |
| Match to the DOJ's own amounts (seized wallets) | **+0.9%, +1.04%, +10.8%** |
| Victim money accounted for | **100%**, to the smallest unit |
| Time Tether took to freeze them after her report | 16 to 20 days (Hound reaches them from her report alone) |
| Reported scam wallets checked this weekend | 963, of which 14 still hold 91,218 unfrozen USDT |
| Real transactions we had never seen, traced end to end | 4 of 4 finished (no hangs, no crashes) |
| Automated tests | 576 passing |

### Proof it works: a real DOJ case, run blind
We tested Hound on a real federal case: *United States v. 4,340,000 Tether* (Northern District of Ohio, 2025). We gave Hound only one victim's six payments and nothing else: no DOJ labels, and Tether's freezes were hidden until after the run.

- Hound reached **all 8 wallets** the FBI named in between, and **all 3 wallets the DOJ seized**.
- Its amounts match the DOJ's own numbers **within about 1%** on two of the seized wallets and 11% on the third.
- Tether froze those wallets **16 to 20 days** after the victim reported. Hound points at them from her report alone.

### How it works (technical)

```
 victim ──call──▶ Cartesia voice agent ──tool: open_case──┐
        ──web───▶ /report form ───────────────────────────┤
                                                          ▼
 screenshot ─▶ Claude vision (extract tx hash / amount / time) ─▶ on-chain validation (receipt or transfer search)
                                                          ▼
                          FIFO taint engine (budget · deadline · audit log)
                                 │                │                 │
                        endpoints + freezes   watchlist        Claude writer
                                 ▼                ▼                 ▼
                         victim case page   exchange /check   police report (cited)
```

**1. Turning a screenshot into a verified payment.** Claude's vision model extracts the transaction hash, or failing that the recipient, amount, token and time. Hound never trusts the extraction: it validates against the chain. A hash is checked against its on-chain receipt; a typed amount is matched against the recipient's real transfers in a time window, and the match must be unique. Fake or mistyped payments are rejected with a plain-language retake message, and "the RPC is down" is reported as a retry, never as "your hash is wrong".

**2. Following the money: FIFO taint accounting.** Each victim payment becomes a *seed lot*. Every wallet keeps a first-in-first-out queue of lots; each outgoing transfer consumes the oldest lots first, so stolen money is split from clean money exactly the way the DOJ attributes funds for its named victims. Everything is computed in **integer base units** (USDT's 6 decimals, ETH's 18), ordered by block number and log index, so rounding can never create or lose a cent; a conservation test checks this to the micro-unit.
- **Swaps.** The DOJ victim paid in ETH, which the scammers swapped to USDT. Hound joins each ETH outflow to the USDT inflow **in the same transaction**, converts the victim's share at the realised rate, and leaves the rounding remainder untainted.
- **Laundering loops.** Funds that cycle back through already-visited wallets are re-queued, not double-counted.
- **Stopping rules.** A branch stops at an exchange, at a wallet Tether froze, at dust, at an exchange-sized address (over 5,000 transfers), or at a cap (max 8 hops, 12 branches per wallet, 400 API calls, 120 s deadline). Every stop is a named reason in the audit log, and an unfinished branch makes the result "partial" rather than silently dropping it.
- **No AI in the decisions.** Classification is rule-based (labels from public exchange datasets, OFAC, an infrastructure allowlist). Claude reads the payment screenshot and writes the reports, and on live traces rewords the rule-based explanations; it never decides a stop or a hold.

**3. Proving it blind.** We rebuilt *US v. 4,340,000 Tether* from the court complaint, which prints wallets truncated (`0xa17…44f0021`). We recovered every full address from public chain data, ruling out deliberate look-alike addresses by amount and date. The engine gets only the victim's six payments. The other DOJ addresses are a **holdout**: the test suite fails if any of them appears in engine code, the case file or the label database, and Tether's freeze events are hidden until after the run. A data cutoff block replays the case exactly as it stood before the freezes.

**4. Warning exchanges, without false accusations.** Every wallet in a traced cluster goes on a watchlist served by a `/check` API that returns **hold, warn or allow** with evidence. A hold needs a verified case: a phone or web report only counts after a person approves it, and exchanges, routers and bridges are never listed. Live victims' addresses are shortened for anyone but the victim, whose case code unlocks their own data.

**5. The police report, with guardrails.** Claude writes the victim and detective summaries using **placeholders, never raw numbers**; code fills in the numbers from the trace. A validator rejects any uncited number, promise of recovery, invented identity or accusation next to an address, retries once within a single deadline, and falls back to a deterministic template if Claude fails.

**6. The voice line.** A Cartesia agent (Claude Haiku) collects the story, infers dates from the current time instead of asking twice, calls an `open_case` tool on our backend (token-authenticated), reads the case code slowly, walks the caller through the upload, and calls `check_upload` to confirm the payment before hanging up.

**Stack:** Python, FastAPI, Next.js 16 on Vercel; Ethereum and Tron data from Etherscan, Blockscout and public RPC nodes with a disk cache and an offline snapshot; Claude (vision + writer); Cartesia (voice). 576 automated tests plus a 91-check end-to-end run.

### Challenges we ran into
- **The DOJ blanks out most of each wallet address** in court documents (like `0xa17…44f0021`), and scammers create look-alike addresses on purpose. We recovered every real address by matching amounts and dates.
- **Our first version silently lost money** when stolen funds looped back through the same wallets. A review caught it, and now we test that every dollar is accounted for.
- **Free blockchain APIs sometimes report errors as success.** We made sure we never save an error as "this wallet had no transactions".
- **Making it usable for an older, scared person.** A phone call instead of forms, one screenshot instead of a transaction code, and a voice agent that waits for the caller to finish talking.

### Accomplishments we're proud of
- Finding all three wallets the DOJ seized, blind, from one victim's report.
- A complete path for a real victim: phone call, screenshot, tracking, warning and police report.
- Being honest about what we know: every result says "reported, not proven", and every dead end is shown.

### What we learned
- The hard part is not tracing; it's getting a victim's report to someone who can freeze the money in time. Across 192 of the wallets Tether froze in 2025, the typical wait was 45 days.
- Plain language matters more than features. Our first screens used words like "hops" and "endpoints"; victims need "where your money went" and "what to do now".

### What's next
- Connecting the warning-list check to real exchanges and wallets.
- Sending the report straight to Tether and the FBI's IC3.
- Free for victims forever; every new report makes the warning list stronger for everyone.

---

## Built with
python · fastapi · next.js · typescript · vercel · anthropic-claude · cartesia · ethereum · tron · usdt · etherscan

## "Try it out" links
- Website: https://houndhelp.vercel.app
- Phone line: (501) 443-1471
- How it works (judge tour): https://houndhelp.vercel.app/how
- Code: https://github.com/A5bhinav/hound

**Try it as the victim:** save https://houndhelp.vercel.app/demo/receipt.png (a real payment from the DOJ case), go to **Report online**, and upload it. Hound finds 101,352 USDT of it, all in wallets Tether froze.

## Video
YouTube link to the 2:00 demo video (docs/VIDEO_PLAN.md).

## What's real and what's simulated
Real: the DOJ case, every wallet and transaction, Tether's freezes, the phone line, the screenshot reading, the live blockchain checks. Replayed: the timing of the 2024 DOJ case (labelled "replay" on screen). Simulated: the exchange withdrawal screen, which shows how an exchange would use Hound's real check.

## Prize tracks to select
Most Technically Complex Hack · Best People-First Hack · Hacker's Choice · The Hyphenated Enterprise: Autonomous Systems for Finance (Hyphenate) · Best Use of Cartesia · Grand Prize: Built for the Real World (Microsoft) · Microsoft Customer Impact Award · Best Security Hack (Armadin) · Anthropic / Claude prize (name from the live site)

(Check each name against the Cal Hacks 13.0 Devpost page before submitting.)

## Image gallery (docs/devpost/, captions as claims)
1. `1-home.png`: Built for the victim first. Call or report online; Hound never asks for money or keys.
2. `2-trace-reveal.png`: From one victim's report, blind, Hound reached all 3 wallets the DOJ seized.
3. `3-exchange-held.png`: A withdrawal to a wallet from the DOJ case is held, with the evidence.
4. `4-police-report.png`: One page a detective can act on. Every number is checked against the trace.
5. `5-proof.png`: Scored blind against the DOJ's own numbers.
6. `6-victim-case-phone.png`: The victim's own case: their payment, where the money is now, each wallet on Etherscan.
