# Hound demo video: the plan

**Target 2:20 (never over 3:00).** For sponsor judges watching on their own, often muted, so every beat carries a burned-in caption. Opens on the moment (Hyphenate asked for exactly this), product on screen by 0:10, a real call, at most five spoken numbers: **$4.4B · 8 of 8 · 3 of 3 · 16 to 20 days · about 1% / 11%**. Everything shown is real except the exchange withdrawal screen, which is labelled a mock.

## Cast: everyone is on camera once and narrates one section

| Who | On camera | Narrates | Why them |
|---|---|---|---|
| **Ishaan** | Cold open + close | 0:00–0:14, 2:05–2:20 | Presents at the table; the face of the pitch |
| **Aaryan** | The victim (on the call) + his own intro line | 0:14–0:45 (the call) | The human beat: he plays a scared victim calling the line |
| **Jinka** | Short intro line at the trace | 0:45–1:35 (trace, Reveal, engine log) | Built the engine; owns "the autonomous investigator" |
| **CK** | Short intro line at the exchange | 1:35–2:05 (exchange hold, police report, proof) | Ran the proof and the QA; owns "we checked it" |

Each on-camera shot is **4 to 6 seconds, one sentence, looking at the lens**, laptop or phone in frame. Film all four in the same spot, same light, so the cuts feel like one team.

## The script

| Time | Picture | Who speaks | Line (spoken) | Caption (burned in) |
|---|---|---|---|---|
| **0:00–0:05** | COLD OPEN. Screen rec **R3**: the trace right after **Reveal what Tether did**, hatched frozen wallets, the banner | Ishaan (VO) | "Hound was never told where this money went. From one victim's report, it found all three wallets the Justice Department seized." | A real DOJ case, run blind |
| **0:05–0:09** | Title card: Hound mark + "Let's track it down." | (music hit) | | HOUND · Trace. Warn. Prevent. |
| **0:09–0:14** | **Ishaan on camera**, then cut to R1 (home hero, cursor moving so the card leans) | Ishaan | "Americans over 60 lost four point four billion dollars to crypto scams last year. Hound is the 911 call for them." | $4.4B lost by Americans over 60 (FBI IC3 2025) |
| **0:14–0:17** | **Aaryan on camera**, phone to his ear | Aaryan | "So I called it." | Real call · real number |
| **0:17–0:38** | Split screen: **left** = Aaryan on the phone (camera); **right** = screen rec **R2**, the laptop's **Report** page filling in live as he talks (case card, steps ticking). Audio = the real call | Agent + Aaryan (real call audio) | Agent: "Hi, this is Hound, here to help. We never ask for money. What happened?" · Aaryan: one line of story ("they said they needed money to fly here from China") · Agent: the case code, slowly · Agent: "go to hound help, dot vercel, dot app" | Why phone first: victims can't read a 64-character hash out loud |
| **0:38–0:45** | Screen rec **R5** (phone): Check my case → code → upload the receipt → "We found your payment" → **Your payment · Verify on Etherscan** | Aaryan (VO) | "I sent a screenshot. Hound found my payment on the blockchain, and I can check it myself." | Claude reads the screenshot · checked on the live Ethereum chain |
| **0:45–0:49** | **Jinka on camera** | Jinka | "This is a real federal case, and Hound saw none of the answers." | US v. 4,340,000 Tether · N.D. Ohio |
| **0:49–1:15** | Screen rec **R3**: the trace unfolding (speed it up 2x), then the click on **Reveal what Tether did** | Jinka (VO) | "It starts from one victim's six payments. No DOJ labels, no freezes. It follows the money through swaps and a laundering loop, and reaches all eight wallets the FBI named, and all three the DOJ seized." (click) "Tether froze them sixteen to twenty days after she reported." | 8 of 8 · 3 of 3 · found blind |
| **1:15–1:35** | Screen rec **R4**: open **Engine log** and scroll it | Jinka (VO) | "Every step is logged, dead ends included. Rules decide where the money goes, never an AI. It's an autonomous investigator you can audit." | The seat it fills: an exchange's fraud investigator |
| **1:35–1:39** | **CK on camera** | CK | "Then we stop the next victim." | |
| **1:39–1:52** | Screen rec **R6**: Exchange page → **Try: A wallet from the DOJ case** → **Withdraw** → **Withdrawal held** + evidence; then **Try: An exchange hot wallet** → **Withdrawal sent** | CK (VO) | "Every wallet in the trail goes on a warning list. When someone tries to pay one, the exchange checks Hound first, and holds it, with the evidence. We warn, we don't seize." | Mock exchange screen · real check API |
| **1:52–2:00** | Screen rec **R7**: Police report, toggle **For the victim** / **For the detective**, scroll | CK (VO) | "Claude writes a one-page report for the police and the victim, and it can only cite numbers that are in the trace." | Every number checked against the blockchain |
| **2:00–2:05** | Screen rec **R8**: Proof page tiles | CK (VO) | "Scored blind against the DOJ's own numbers: within about one percent on two wallets, eleven on the third." | Scored against the DOJ complaint |
| **2:05–2:13** | **All four on camera together**, then cut to the home page | Ishaan | "Hound. The 911 call for crypto scam victims." | houndhelp.vercel.app · (501) 443-1471 |
| **2:13–2:20** | End card: logo, team names, sponsors | (music out) | | Voice: Cartesia · Screenshot reading + reports: Claude · Ishaan · Jinka · CK · Aaryan |

Spoken numbers check: $4.4B (0:09), 8 of 8 / 3 of 3 (1:05), 16 to 20 days (1:12), about 1% / 11% (2:00). Nothing else.

## What to record (in this order)

**Before recording:** `make demo` up, web on :3000 rebuilt, ngrok up. Laptop at **1920×1080, browser zoom 125%, bookmarks bar hidden, Do Not Disturb on**, other tabs closed. Click **Reset demo** at the bottom of /how. Use macOS screen recording (Cmd+Shift+5), full screen, with the cursor shown.

| Rec | Device | What to do, exactly | Notes |
|---|---|---|---|
| **R1** | Laptop | Open http://localhost:3000. Hold 3 s, slowly move the cursor across the hero so the card leans | 8 s is plenty |
| **R2** | Laptop + phone | Laptop: open http://localhost:3000/intake (the Report page). Phone on speaker: Aaryan calls **(501) 443-1471** and does the call below. Record the laptop screen the whole time; record the phone audio too (QuickTime audio, or a second phone filming) | The case card fills in live: that's the shot |
| **R3** | Laptop | http://localhost:3000/cases/ohnd-replay-ah. Let the trail unfold, then click **Reveal what Tether did** once it lights up. Hold 4 s on the frozen wallets | Used twice: the cold open (the end of it) and the 0:49 beat |
| **R4** | Laptop | Same page, scroll down, open **Engine log · N steps**, scroll it slowly | 10 s |
| **R5** | Phone | Screen-record the phone: houndhelp.vercel.app → **Check my case** → type the code from the call → **Send a picture of your payment** → **Choose the picture of my payment** → pick the saved receipt (houndhelp.vercel.app/demo/receipt.png, saved earlier) → wait for "We found your payment" → **See what we found** → scroll to **Your payment · Verify on Etherscan** and tap it once | Do it during or right after the R2 call, with the same code |
| **R6** | Laptop | http://localhost:3000/exchange → **Try: A wallet from the DOJ case (on the warning list)** → **Withdraw** → hold on **Withdrawal held** → **Try: An exchange hot wallet** → **Withdraw** → **Withdrawal sent** | |
| **R7** | Laptop | http://localhost:3000/cases/ohnd-replay-ah/packet → scroll → **For the victim** → scroll | Open it once before recording so it loads instantly |
| **R8** | Laptop | http://localhost:3000/proof, hold, slow scroll | |
| **Faces** | Phone camera, landscape | 4 solo shots (lines above) + 1 group shot. Same spot, same light, laptop or Hound on screen behind | Shoot 3 takes each |

**The call for R2 (Aaryan is the caller; keep it short to save the free-plan minutes):**
1. Agent greets. Aaryan: "Hi, I got scammed."
2. Name: "Aaryan."
3. App: "a blue app with a C on it." Contact: "they messaged me on WeChat, about five months ago."
4. "I sent it from that same app."
5. What happened: "They said they needed money to fly here from China, and they never came. I sent about thirty-three ETH."
6. Listen to the case code (twice) and the website. Do R5 on the phone. Say "I sent it" when the upload is done.
7. The agent confirms the payment and says goodbye on its own.

## Edit notes

- **Captions burned in** on every beat (CapCut auto-captions, then fix the proper nouns: Hound, Tether, Cartesia, Etherscan). Large, white, bottom third.
- **Speed:** cut every loading wait; play the trace unfold at 2x; no dead air over 0.5 s.
- **Music:** low, steady, no lyrics; one hit on the title card at 0:05; duck it under every voice.
- **Privacy:** only our line (501) 443-1471 on screen. No live-case address in full (the site already shortens them), no keys, no terminal.
- **Honesty:** the exchange screen keeps its "Mock exchange screen" caption. Say "replay" or "real DOJ case" for the trace, never "live" for it.
- **Export:** 1920×1080, 30 fps, H.264. Upload to YouTube (unlisted is fine) **by 2 AM**, link it on Devpost, and put a copy on the demo laptop's desktop as the backup video.

## Timeline tonight

| By | What | Who |
|---|---|---|
| 7:30 PM | Faces shot (5 shots) | all four |
| 8:00 PM | R1, R3, R4, R6, R7, R8 recorded | Ishaan |
| 8:30 PM | The call: R2 + R5 (one take, two if needed) | Aaryan + Ishaan |
| 11:00 PM | First cut, shared in the chat | Ishaan |
| 1:00 AM | Final cut with captions | Ishaan |
| 2:00 AM | On YouTube, linked on Devpost, copy on the desktop | Ishaan + Aaryan |
