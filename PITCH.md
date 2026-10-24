# Hound pitch (Cal Hacks 13.0)

Every number below is verified (source in brackets). Don't say anything that isn't here. If a judge asks something not covered, say "I don't know, here's what we measured instead."

## 2-minute version (default, demo first)

**0:00 Open (10 s).**
"Americans over 60 lost 4.4 billion dollars to crypto scams last year. Hound starts from one victim's report and follows the money. We never touch money and never ask for keys." [FBI IC3 2025]

**0:10 The replay (50 s). Screen: trace graph.**
"This is a real federal case: US versus 4.34 million Tether, Northern District of Ohio. The DOJ printed the wallets truncated, like 0xa17-dot-dot-dot. We recovered every full address from public chain data.
We start from one victim, A.H., and her six real ETH sends. Hound sees nothing else: no DOJ labels, and Tether's freezes are hidden from it.
Watch it work: her ETH is swapped to USDT in the same transaction at three wallets, then it moves through a laundering loop, then a consolidation wallet.
Hound reaches all 8 intermediate wallets the FBI named that it wasn't given, and all three wallets the DOJ seized."
[engine test: test_reaches_doj_seized_wallets_blind]

**1:00 The reveal (15 s).** Click reveal.
"And here's what Hound didn't know: Tether froze these wallets 16 to 20 days after A.H. reported to the FBI on June 5 [complaint ¶ 38; freezes Jun 21 and 25]. Hound points at them from her report alone."

**1:15 The hold (20 s). Screen: exchange withdrawal.**
"The save happens at the exchange. A victim tries to send to a wallet in this cluster, and Hound says hold, with the evidence. One report protects the next person."

**1:35 Proof and honesty (20 s). Screen: proof panel.**
"Scored against the DOJ's own numbers for A.H.: two of the three seized wallets within 1 percent, the third within 11. Every victim dollar is accounted for. Every hop has a confidence, every dead end is on screen, and the packet can only cite numbers that are in the trace. A test fails the build otherwise."

**1:55 Close (5 s).** "Hound. The 911 call for crypto scam victims."

## 3-minute version: add these
- **The call (30 s, before the replay).** Play the recorded intake clip (live only for Cartesia judges): the victim tells the story by phone, the agent reads out a case code, she uploads a screenshot, the case card fills in. "Nobody reads a 64-character hash over the phone, so we don't ask them to."
- **The packet (20 s, after the hold).** One page for a detective: every hop, every transaction, freeze status, which exchange and Tether to contact, "reported, not proven".
- **Why now (10 s).** "Tether can freeze USDT on one law enforcement request. In 2025 it froze 1.26 billion dollars across 4,163 addresses. The bottleneck is getting a victim's report to that request fast." [BlockSec 2025]

## Q&A
**"Isn't this just Chainalysis / TRM?"**
"They sell to agencies and exchanges, and TRM launched an AI tracing agent in March. Hound is the front door those tools don't have: it starts from a scared victim, produces a packet a local detective can send, and spreads the warning past the reported address. Chainabuse is an input for us, not a competitor."

**"How did you get the start address? Isn't that cheating?"**
"The DOJ printed it in paragraph 69, truncated. We resolved it on chain by amount and date. The engine got nothing else: the other 14 DOJ addresses are a holdout, and a test fails the build if any of them appears in engine code or the label database."

**"Why is A-9 off by 11 percent?"**
"We use first-in-first-out, the DOJ's method for its named victims, on public data only. The DOJ also had subpoena data and used other methods for some victims (LIFO, PIFO). We show the gap instead of tuning it away: A-7 is within 0.9 percent and A-8 within 1.0."

**"What's FIFO and why that?"**
"First in, first out: the oldest money in a wallet leaves first. It's the method the DOJ used for its named victims in this case."

**"Could it accuse an innocent wallet?"**
"Exchange wallets are never on the watchlist. A hold needs a Tether freeze or a high-confidence trace from a verified send. Reports alone never hold, low confidence only warns, and nothing is published: findings go to IC3, Chainabuse or the exchange, labelled reported, not proven."

**"Where's the AI?"**
"Claude does two jobs where code can't: it explains each wallet's behaviour, and it writes the victim's and detective's summaries. It never decides a stop or a hold. The writer can only use placeholders for numbers, and a validator rejects anything it can't verify, including promises of recovery."

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
