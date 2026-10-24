# Q&A prep (CK) — the follow-ups PITCH.md does not cover. Every number has a source.

**"Your backtest says 45 days. What does that measure?"**
"For 200 of the 657 Ethereum USDT addresses Tether froze in 2025, the time from the first USDT arriving to the freeze: median 45 days, 10th percentile 36 hours, 90th percentile about 13 months. And by the freeze, a median 44 percent of what came in had already left. Caveat we print on screen: it only measures addresses Tether did freeze, so the true picture for everything it never froze is worse." [data/proof/backtest.json, seed 13, OFAC addresses excluded]

**"Why not just say Tether froze 54 percent?"**
"That's BlockSec's number about burned funds, and we cite it as theirs. Ours is a different measurement we can reproduce from the chain." [BlockSec 2025 report]

**"You found a wallet holding 853K USDT. Why isn't it the headline?"**
"Because one Chainabuse report points at it, and that's all. The wallet also holds PYUSD, USDC, cbBTC and cbETH and makes DeFi calls, so it could be a real person or a fund that a scam used, or a treasury. We don't name a wallet the scammer's on one report. It appears only as an anonymous row in the weekend-scan stat, labelled reported, not proven. That restraint is the product."

**"Could someone file a fake report and get an innocent wallet held?"**
"No. A client-posted case can be traced but never mints a hold. Intake validates the send on chain, which proves the payment exists, not that the caller made it, so an operator has to approve the case before it feeds the watchlist. Exchange, sanctioned and infrastructure addresses are never held at all." [api security rules, intake approve step]

**"What about address poisoning / lookalike addresses?"**
"We hit it on day one: the DOJ printed addresses truncated, and poison lookalikes share those prefixes and suffixes. Zero-value and dust transfers are dropped before anything is matched, and the scoreboard matches full addresses only. Three lookalikes sat in our own fixture." [proof/resolve_ohnd.py]

**"Why 11 wallets in one place and 8 in another?"**
"The complaint names 15 wallets. Four are where the victim's own sends start and land, so the engine is given those. The 11 others are the holdout. Of those, 8 are intermediates and 3 are the seized wallets, and the engine reached all 11 blind."

**"Does it work on Tron? That's where most USDT scams run."**
"The adapter and the Tron freeze lookup work (50 ms, offline). We kept the demo on Ethereum because that's where the public DOJ answer key is. Tether froze 3,509 addresses on Tron in 2025, so it's the obvious next case." [BlockSec: 3,509 Tron / 657 Ethereum]

**"The live case: how fresh, how fast?"**
"Reported on Chainabuse on October 21. Victim sent on October 8 and 15. The trace runs in under a second from cache, about 17 seconds cold. Her first 96,028 USDT hit a Coinbase deposit address and was swept into Coinbase 10 within four minutes. That's the window we're talking about."

**"What happens to the victim's data?"**
"Phone numbers are never stored. Live addresses are truncated for anyone not on the operator's machine, the story is never shown off-machine, and nothing is published: packets go to IC3, Chainabuse and the exchange. The repo can't even pack a live address into its snapshot."

**"What do you need from an exchange to make the hold real?"**
Use the Coinbase booth quotes (collect Saturday, attribute by role). Fallback: "A deposit address, the inbound transaction hashes, amounts and times, and the chain of hops from a verified victim send. That's exactly what the packet contains."

**"How many Chainabuse API calls did this take?"**
"Zero. Candidates were hunted by hand on the site; the API has a 10-call-a-month free tier and we never spend it on a per-address lookup."

**"If I give you my own transaction hash right now?"**
"Paste it in. It traces live with a budget and a deadline; if a branch can't be loaded, the packet says so. It will never hold anything, because a judge's case isn't a verified victim case." [judge case path in make e2e]

## Numbers to have cold
- $11.4B crypto losses 2025, $7.2B crypto investment fraud, $4.4B lost by 60+ to crypto [IC3 2025 PDF]
- 12,444 people over 60 lost over $100K to scams (all kinds) [IC3 2025]
- Operation Level Up: 3,780 notified in 2025, about $225M prevented, 78% didn't know; cumulative about $660M [FBI via press]
- Tether 2025: 4,163 addresses, $1.26B frozen; 3,509 Tron, 657 Ethereum [BlockSec]
- DOJ case: 38 victims/accounts, finals frozen Jun 21 and 25 2024, seized 4,340,000 / 3,290,000 / 577,578 USDT [complaint]
- Scoreboard: A-7 +0.9%, A-8 +1.0%, A-9 +10.8%; 8/8 intermediates, 3/3 seized, blind
- Backtest: median 45 days, p10 36 h, p90 ~13 months, 44% escaped, n=192
- Weekend scan: 963 reported addresses checked on chain, 14 hold unfrozen USDT, 91,217.87 USDT
