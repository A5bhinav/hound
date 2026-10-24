# Demo day runbook (Sun Oct 25)

One laptop runs the demo (Ishaan's). Hard deadline for Devpost is **9:00 AM**; be at the venue by 8 AM. Judging **10:30 AM to 12:30 PM**, all four of us at the table.

## Sun 8 AM checklist
- [ ] `git checkout main && git pull --ff-only`; `make test` is green; `make e2e` ends with `0 warn, 0 fail` (needs `cd web && npm ci` once; it builds into `web/.next-e2e`, so the demo's `web/.next` is untouched).
- [ ] Repo-root `.env` has `ANTHROPIC_API_KEY`. After `make demo`, run the replay once and GET `/cases/ohnd-replay-ah/packet`: expect `"source": "claude"`. If it says `template`, either the key is not loaded (`grep -c '^ANTHROPIC_API_KEY=.' .env` must print 1) or Claude's draft failed the validator twice (the backend log says "fell back to the template"); the packet is still correct, but do not say "Claude wrote this".
- [ ] Phone hotspot is the primary network. Venue Wi-Fi is the backup.
- [ ] `caffeinate -dims` running (the laptop must not sleep).
- [ ] Focus / Do Not Disturb on. Close Claude Code and anything holding API keys. Browser zoom 125%.
- [ ] `data/cases_live/` (AirDropped from Jinka, never committed) is in the repo root.
- [ ] `cd backend && .venv/bin/python -m hound.chain.preflight --live` ends with `ALL GOOD`. Offline it checks the DOJ replay numbers (317,403.01 / 47,702.92 / 12,077.78), every live case from the bundle, and `/check`, with and without an Etherscan key. `--live` prints each live wallet's USDT balance and Tether freeze status right now, plus the time: say "checked h:mm AM".
- [ ] Live case `live-mindchain-binance` traces offline from Jinka's bundle (`data/cases_live/`, gitignored, must be on the demo laptop). No gold ending this weekend: CK's hunt found no clean holding wallet.
- [ ] Charger, power strip, backup video on the desktop.

- [ ] After `make demo` is up: trace the replay, then open BOTH packets once (victim + detective). Claude takes about 15 s and 25 s; after that they are cached per trace and open instantly. Expect `source: claude`.

## Start (2 terminals, in this order)
```
# terminal 1, repo root: backend on the committed snapshot
make demo                                   # HOUND_CACHE_MODE=prefer_cache on :8000

# terminal 2: web
cd web && npm ci && rm -rf .next && HOUND_API_URL=http://localhost:8000 npm run build && npm run start    # http://localhost:3000, bound to 127.0.0.1 only (npm ci once per clone; rebuild after any env change)
```
`web/.env.local` must have `HOUND_DATA=` (empty) and `HOUND_API_URL=http://localhost:8000`.
Health check: open http://localhost:8000/health and expect `"ok": true`.

## Public access + live intake (Cartesia)
The public website is **https://houndhelp.vercel.app** (Vercel project ish-c/houndhelp, deployed from `web/`). It never changes on restart. It reaches the laptop's backend through the reserved ngrok domain (`HOUND_API_URL` in the Vercel project), so the laptop, `make demo` and ngrok must be up.
```
# terminal 3: backend for the website and Cartesia's tool calls (stable reserved domain)
ngrok http 8000 --url=<reserved ngrok domain>
# redeploy the website after a web/ change:
cd web && vercel deploy --prod --yes
```
1. `.env` has `PUBLIC_BASE_URL=https://houndhelp.vercel.app` and `HOUND_SPOKEN_SITE="hound help dot vercel dot app"` (the agent reads the site out when it can't text). Restart the backend after changing either.
2. Register the voice agent's tool: `python scripts/cartesia_agent.py --tool-url https://<ngrok domain>/intake/voice/story`.
3. Test once before judging: call (989) 800-8367, hear the case code and the site, open houndhelp.vercel.app on a phone on cellular, **Check my case**, type the code, send a screenshot, and watch **Report** go to "Send confirmed on chain".
4. On the operator laptop, click **Approve: I reviewed this send** on the Report page. Only approved cases can cause exchange holds.

Viewers on the public host see live cases with shortened addresses and no story text, and cannot reset the demo. That is by design.

## The 2-minute click path, in story order (script: PITCH.md)
The top bar is the story: **1 Report → 2 Follow the money → 3 Stop the next victim → 4 Police report**, then **Proof it works**. Say the step name as you click it.

The site has two front doors. **http://localhost:3000** is the victim's: the hero (Report a scam / How it works) and, one scroll down, Call us / Report online / Check my case and what Hound will never ask for. Show it for 5 seconds ("this is what a victim sees", scroll once), then click **How it works** in the top bar for the tour.

0. **How Hound works** (http://localhost:3000/how): read the one-liner, point at the 4 "How it works" cards. Click **Walk through it: 1 Report →**.
1. **Report.** The page shows the Hound number, (989) 800-8367. Live: a judge calls it, tells a short story, hears the case code and houndhelp.vercel.app, and sends the payment screenshot from **Check my case** (or types A.H.'s first tx hash). The case card fills in; then **Next: Follow the money →**. No call possible: **Play a sample call** (labelled as a replay), or **Next: Follow the money →** at the bottom.
2. **Follow the money** (the DOJ case, Victim A.H.). The trace streams in, then the transfers unfold column by column. Once the last one is drawn, click **Reveal what Tether did**: the 3 last wallets turn hatched ("Tether froze it") and the headline reads "Tether froze 3 of these wallets 16 to 20 days after the victim's report". Click **Next: Stop the next victim →**.
3. **Stop the next victim.** **Try: A wallet from the DOJ case (on the warning list)** → **Withdraw**: **Withdrawal held**, with the evidence. **Try: An exchange hot wallet** gives **Withdrawal sent**. Click **Next: Police report →**.
4. **Police report.** The detective's copy; **For the victim** switches copy ("writing…" while Claude writes); **Print or save as PDF** works. Click **Next: See the proof on a real DOJ case →**.
5. **Proof it works:** all 3 seized wallets and 8 of 8 in between, found blind; A-7 and A-8 within about 1%, A-9 within 11%.
6. Before the next judge: **Reset demo** at the bottom of http://localhost:3000/how (click twice). It calls `POST /demo/reset`.

## A judge who wants to try it as a victim
Kit and full steps: **docs/demo-kit/README.md**. In short: they call (989) 800-8367 with any story, save **houndhelp.vercel.app/demo/receipt.png** (A.H.'s real 33 ETH payment), upload it on their case page, and see 101,352 USDT followed, all frozen by Tether.

### Typing instead of the screenshot
On their phone, at the public web URL: **Report online** → answer the questions → **Let me type it instead** and paste A.H.'s first tx hash (`0x39f5…1adc`, full value in `examples/ohnd_replay.case.json`) → "We found your payment" → **See what we found**: where the money went, what to do now, and their own report (unredacted, because they hold the case code).

## When something breaks
| Symptom | Do this |
|---|---|
| Trace never finishes | `curl localhost:8000/health`; if dead, restart `make demo`. If still stuck, play the backup video from the trace step |
| Trace status `partial` | Say so: "one branch couldn't be fetched, and Hound shows it rather than guessing." Both packets open with a PARTIAL TRACE banner that lists the incomplete branches. Keep going |
| Judge gives their own tx hash | Create the case (it traces live with a call budget). It will NOT feed the watchlist (unverified cases never cause holds); say that is by design |
| No internet at all | Both the DOJ replay (committed snapshot) and the live case (local bundle) run with zero network calls |
| Claude API down / no key | Packets fall back to the deterministic template (`source: template`) within about 20 seconds; every number is still verified. Wallet explanations keep their rule text. With a key set, each trace also asks Claude to reword those explanations, so a stalled network slows the trace too: unset the key if the venue network is bad |
| UI shows OFFLINE | `HOUND_DATA=fixture` is set in `web/.env.local`; clear it and rebuild |
| Intake page says "intake backend isn't running" | The backend is down or was started without the intake routes: `curl localhost:8000/health`, restart `make demo`. Meanwhile use **Play a sample call** |
| "Reveal what Tether did" is greyed out | The hops are still unfolding; wait for the last column, or click **Skip to the end** |

## Never on screen
- A live-case address in full (truncate it), and never call a reported wallet "the scammer" (reported, not proven).
- "Sitting there right now" about the DOJ case (it is a replay).
- Any API key, `.env`, or terminal with secrets.
