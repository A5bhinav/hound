# Devpost: paste-ready (one section per Devpost field)

Every number here is checked against the code and data (sources: PITCH.md, BRIEF.md §2, data/proof/). Keep the wording simple; if you change a number, check it first.

---

## Project name
Hound

## Elevator pitch (Devpost limit: 200 characters)
The 911 call for crypto scam victims. Hound follows stolen crypto to where it can still be frozen, warns exchanges before the next victim pays, and writes the police report.

---

## About the project

### Inspiration
Americans over 60 lost $4.4 billion to crypto scams last year (FBI IC3, 2025). Most of these are "pig-butchering" scams: someone builds a fake friendship or romance, then talks the victim into a fake investment app.

When it happens, the victim usually calls local police, who often can't trace crypto. Professional tracing tools exist, but they're sold to governments and exchanges, not to victims. Meanwhile, Tether can freeze stolen USDT with one request from law enforcement. The money is often still sitting somewhere it could be frozen. Nobody connects the victim to that request in time.

We built Hound to be that connection, and to use one victim's report to protect the next person.

### What it does
1. **Report.** A victim calls our phone line (a voice agent built on Cartesia) or reports online. They tell their story in their own words and send one screenshot of their payment. Nobody has to read a long transaction code out loud.
2. **Follow the money.** Hound reads the screenshot, finds the payment on the blockchain, and follows the money wallet by wallet to where it ended up: an exchange, a wallet that can still be frozen, or a wallet Tether already froze.
3. **Stop the next victim.** Every wallet in the trail goes on a warning list. When someone tries to send money from an exchange to one of those wallets, the exchange can check Hound first and hold the payment, with the evidence attached.
4. **Police report.** Hound writes a one-page report for the detective and a plain-language copy for the victim: every transfer, where the money is now, and who to contact (Tether, the exchange, the FBI's IC3).

The victim gets a case code. With it they can come back any time to see what we found, what to do next, and their report. Every payment and wallet links to Etherscan, so they can check it themselves.

### Proof it works: a real DOJ case, run blind
We tested Hound on a real federal case: *United States v. 4,340,000 Tether* (Northern District of Ohio, 2025). We gave Hound only one victim's six payments and nothing else: no DOJ labels, and Tether's freezes were hidden until after the run.

- Hound reached **all 8 wallets** the FBI named in between, and **all 3 wallets the DOJ seized**.
- Its amounts match the DOJ's own numbers **within about 1%** on two of the seized wallets and 11% on the third.
- Tether froze those wallets **16 to 20 days** after the victim reported. Hound points at them from her report alone.

### How we built it
- **The tracing engine (Python).** Follows the money step by step using "first in, first out" accounting, the same method the DOJ used for its named victims. Rules decide every step; an AI never decides where the money went or whether to hold a payment. Every step is logged, including dead ends.
- **Blockchain data.** Ethereum and Tron data from public sources (Etherscan, Blockscout, public RPC nodes), with Tether's freeze records. A saved snapshot lets the DOJ case run with no internet.
- **Claude (Anthropic).** Reads the payment screenshot, and writes the police report in plain English. It can only use numbers that are in the trace: a checker rejects anything else, including promises to get money back, and a fixed template takes over if Claude is unavailable.
- **The voice line (Cartesia).** Takes the victim's story, opens the case, reads out the case code and the website, and walks them through sending the screenshot.
- **The app.** A FastAPI backend and a Next.js website on Vercel (houndhelp.vercel.app).

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
Most Technically Advanced · Best People-First Social Impact · Claude for Public Benefit · Armadin Best Security Hack · Hyphenate (Autonomous Systems for Finance) · Cartesia · Microsoft Built for the Real World · Hacker's Choice

(Check each name against the Cal Hacks 13.0 Devpost page before submitting.)

## Image gallery (docs/devpost/, captions as claims)
1. `1-home.png`: Built for the victim first. Call or report online; Hound never asks for money or keys.
2. `2-trace-reveal.png`: From one victim's report, blind, Hound reached all 3 wallets the DOJ seized.
3. `3-exchange-held.png`: A withdrawal to a wallet from the DOJ case is held, with the evidence.
4. `4-police-report.png`: One page a detective can act on. Every number is checked against the trace.
5. `5-proof.png`: Scored blind against the DOJ's own numbers.
6. `6-victim-case-phone.png`: The victim's own case: their payment, where the money is now, each wallet on Etherscan.
