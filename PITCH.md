# Hound pitch (Cal Hacks 13.0)

Every number below is verified (source in brackets). Don't say anything that isn't here. If a judge asks something not covered, say "I don't know, here's what we measured instead."

## 3-minute version (MAIN: Cal Hacks 13.0 is 3 min pitch + 2 min Q&A, live demo required)
Each step carries one **why** line for the Intentionality criterion ("who it's for and why it works the way it does"). Say it; it's short on purpose.

**0:00 Open (15 s). Screen: houndhelp.vercel.app.**
"Americans over 60 lost 4.4 billion dollars to crypto scams last year. [FBI IC3 2025] Hound follows stolen crypto and stops it moving again. This is the front door, and it's built for the victim first: call us, or report online."
**Why:** "Most victims are older and panicking, so the first screen is two big choices and what we will never ask for. Scammers follow up with fake recovery offers, so we say that up front."

**0:15 Step 1, Report (35 s). Screen: phone + Report page.**
"A victim calls this number. Our voice agent takes the story, gives them a case code and our website, and walks them through sending a screenshot of the payment." (A judge or teammate uploads the demo receipt from docs/demo-kit.) "Hound just checked that payment on the live Ethereum chain. A made-up one gets rejected."
**Why:** "Nobody reads a 64-character hash over the phone, so we never ask them to. The story can be anything; the payment has to be real."

**0:50 Step 2, Follow the money (40 s). Screen: trace.**
"This is a real federal case: US versus 4.34 million Tether, Northern District of Ohio. We start from one victim, A.H., and her six real sends. Hound sees nothing else: no DOJ labels, and Tether's freezes are hidden from it. Watch her money move: swapped to USDT, through a laundering loop, into a consolidation wallet. Hound reaches all 8 wallets the FBI named in between, and all three wallets the DOJ seized."
**Why:** "First in, first out, the method the DOJ used for its named victims, so a detective can check every number."
[engine test: test_reaches_doj_seized_wallets_blind]

**1:30 The reveal (15 s).** Click **Reveal what Tether did**.
"And here's what Hound didn't know: Tether froze these wallets 16 to 20 days after A.H. reported to the FBI on June 5 [complaint ¶ 38; freezes Jun 21 and 25]. Hound points at them from her report alone."

**1:45 Step 3, Stop the next victim (25 s). Screen: exchange withdrawal.**
"Every wallet in this trail goes on a warning list. When the next person tries to withdraw to one of them, the exchange asks Hound first, and the payment is held, with the evidence. One report protects the next person."
**Why:** "A hold needs a verified case: a phone report only counts after a person approves it, and exchanges are never on the list, so an innocent wallet never gets frozen off one phone call."

**2:10 Step 4, Police report (20 s). Screen: report.**
"The detective gets one page: every transfer, where the money sits, and who to contact, Tether, the exchange and the FBI's IC3."
**Why:** "Claude writes it in plain English, but it can only cite numbers that are in the trace. A checker rejects anything else, including promises of recovery, and a fixed template takes over if Claude is down."

**2:30 A real case from this month (15 s). Screen: live-mindchain-binance.**
"A real pig-butchering report filed this month: 11,082 dollars of USDT, and 85 percent of it reached Binance within hours, through a wallet that sweeps into Binance's hot wallet, most likely a deposit address. Binance can freeze that account."

**2:45 Proof it works (10 s). Screen: proof.**
"Scored against the DOJ's own numbers: two of the three seized wallets within about 1 percent, the third within 11. Every victim dollar is accounted for."

**2:55 Close (5 s).** "Hound. The 911 call for crypto scam victims."

## 2-minute version (backup if time is cut; same order)

**0:00 Open (15 s). Screen: home.**
"Americans over 60 lost 4.4 billion dollars to crypto scams last year. [FBI IC3 2025] Hound follows stolen crypto and stops it moving again, in four steps, the ones across the top: a victim reports, Hound follows the money, exchanges stop the next victim, and police get a report. We never touch money and never ask for keys."

**0:15 Step 1, Report (15 s). Screen: Report.**
"A victim calls this number. Our voice agent takes the story, sends them to hound help dot vercel dot app, and walks them through sending a screenshot of the payment. Nobody reads a 64-character hash over the phone." (Live call if a judge wants to try it; otherwise **Next: Follow the money**.)

**If a judge calls (adds about 60 s; kit in docs/demo-kit).** "Make up any story. The payment has to be real, so you will be A.H., the victim in the DOJ case: save this receipt of her real payment." They upload it. "Hound just checked that payment on the live Ethereum chain. A fake one gets rejected." On their case page: "It followed 101,352 dollars of that one payment, and all of it is in wallets Tether froze. That is one of her six payments; here is the whole case." Then **How Hound works**.

**0:30 Step 2, Follow the money (35 s). Screen: trace.**
"This is a real federal case: US versus 4.34 million Tether, Northern District of Ohio. We start from one victim, A.H., and her six real sends. Hound sees nothing else: no DOJ labels, and Tether's freezes are hidden from it. Watch her money move: swapped to USDT, through a laundering loop, into a consolidation wallet. Hound reaches all 8 wallets the FBI named in between, and all three wallets the DOJ seized."
[engine test: test_reaches_doj_seized_wallets_blind]

**1:05 The reveal (15 s).** Click **Reveal what Tether did**.
"And here's what Hound didn't know: Tether froze these wallets 16 to 20 days after A.H. reported to the FBI on June 5 [complaint ¶ 38; freezes Jun 21 and 25]. Hound points at them from her report alone."

**1:20 Step 3, Stop the next victim (15 s). Screen: exchange withdrawal.**
"Every wallet in this trail goes on a warning list. When the next person tries to withdraw to one of them, the exchange asks Hound first, and the payment is held, with the evidence. One report protects the next person."

**1:35 Step 4, Police report (10 s). Screen: report.**
"And the detective gets one page: every transfer, where the money sits, and who to contact, Tether, the exchange and the FBI's IC3. It can only cite numbers that are in the trace."

**1:45 Proof it works (10 s). Screen: proof.**
"Scored against the DOJ's own numbers: two of the three seized wallets within about 1 percent, the third within 11. Every victim dollar is accounted for."

**1:55 Close (5 s).** "Hound. The 911 call for crypto scam victims."

## Extra beats (use only if a judge asks)
- **The live case (25 s, after the DOJ proof).** Pick **live-mindchain-binance**: a real pig-butchering report filed this month. "This victim sent 11,082 dollars of USDT in October. Hound followed it into a laundering hub, and 85 percent of it reached Binance within hours, through an unlabelled wallet that sweeps straight into Binance's hot wallet, most likely a Binance deposit address. Binance can tell who owns that deposit address and can freeze the account. The request is ready." Never say the money is still sitting there unfrozen: it reached an exchange. Show the address truncated.
- **The call (30 s, before the replay).** Play the recorded intake clip (live only for Cartesia judges): the victim tells the story by phone, the agent reads out a case code, she uploads a screenshot, the case card fills in. "Nobody reads a 64-character hash over the phone, so we don't ask them to."
- **The packet (20 s, after the hold).** One page for a detective: every hop with its transaction count and confidence, every endpoint with its freeze status, who to contact (Tether, IC3, the exchange), a banner naming any incomplete branch, "reported, not proven".
- **Why now (10 s).** "Tether can freeze USDT on one law enforcement request. In 2025 it froze 1.26 billion dollars across 4,163 addresses. The bottleneck is getting a victim's report to that request fast." [BlockSec 2025]

## Q&A
**"Isn't this just Chainalysis / TRM?"**
"They sell to agencies and exchanges, and TRM launched an AI tracing agent in March. Hound is the front door those tools don't have: it starts from a scared victim, produces a packet a local detective can send, and spreads the warning past the reported address. Chainabuse is an input for us, not a competitor."

**"How did you get the start address? Isn't that cheating?"**
"The DOJ printed it in paragraph 69, truncated. We resolved it on chain by amount and date. The engine got nothing else: the other 11 DOJ addresses are a holdout. Our test suite fails if any of them appears in engine code or the replay case, and a guard keeps them out of the label database."

**"Why is A-9 off by 11 percent?"**
"We use first-in-first-out, the DOJ's method for its named victims, on public data only. The DOJ also had subpoena data and used other methods for some victims (LIFO, PIFO). We show the gap instead of tuning it away: A-7 is within 0.9 percent and A-8 within 1.04."

**"What's FIFO and why that?"**
"First in, first out: the oldest money in a wallet leaves first. It's the method the DOJ used for its named victims in this case."

**"Could it accuse an innocent wallet?"**
"Exchange wallets are never on the watchlist. A hold needs a Tether freeze or a high-confidence trace from a verified send. Reports alone never hold, low confidence only warns, and nothing is published: findings go to IC3, Chainabuse or the exchange, labelled reported, not proven."

**"Where's the AI?"**
"Claude does two jobs where code can't: it rewords each wallet's rule-based explanation in plain English, and it drafts the victim's and detective's summaries. It never decides a stop or a hold. The writer can only use placeholders for numbers, and a validator rejects anything it can't verify, including promises of recovery. If Claude is down, a fixed template writes the same packet."

**"Would you hire it? For which seat?"** (Hyphenate)
"An exchange fraud or AML investigator. Read-only access, it can't move money, every step is in an audit log, and it warns instead of holding when it's unsure."

**"Business model?"**
"Victims are free forever. Exchanges and wallets pay per check before a withdrawal; every free victim case makes the watchlist better."

**"What's real vs simulated?"**
"Real: the DOJ case, every address, every transaction, Tether's freezes, the swaps. Replayed: the timing (it happened in 2024, marked replay on screen). Simulated: the exchange withdrawal screen."

## Rules on stage
- Say "reached the same wallets DOJ seized", never "reproduced the FBI's trace" (they also had subpoenas).
- Say "replay" for the DOJ case. Never "the money is sitting there right now".
- 12,444 people over 60 lost over $100K **to scams** (all kinds), not "to crypto".
- Never show a live, unfrozen address in full (video, slides, Devpost).
