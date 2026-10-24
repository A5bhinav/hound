# Demo day runbook (Sun Oct 25)

One laptop runs the demo (Ishaan's). Hard deadline for Devpost is **9:00 AM**; be at the venue by 8 AM. Judging **10:30 AM to 12:30 PM**, all four of us at the table.

## Sun 8 AM checklist
- [ ] `git pull` on main; `make test` is green.
- [ ] Repo-root `.env` has `ANTHROPIC_API_KEY`. After `make demo`, run the replay once and GET `/cases/ohnd-replay-ah/packet`: expect `"source": "claude"`. If it says `template`, the key is not loaded; the packet is still correct, but do not say "Claude wrote this".
- [ ] Phone hotspot is the primary network. Venue Wi-Fi is the backup.
- [ ] `caffeinate -dims` running (the laptop must not sleep).
- [ ] Focus / Do Not Disturb on. Close Claude Code and anything holding API keys. Browser zoom 125%.
- [ ] Live case `live-mindchain-binance` traces offline from Jinka's bundle (`data/cases_live/`, gitignored, must be on the demo laptop). No gold ending this weekend: CK's hunt found no clean holding wallet.
- [ ] Charger, power strip, backup video on the desktop.

## Start (2 terminals, in this order)
```
# terminal 1, repo root: backend on the committed snapshot
make demo                                   # HOUND_CACHE_MODE=prefer_cache on :8000

# terminal 2: web
cd web && npm run build && npm run start    # http://localhost:3000 (rebuild after any env change)
```
`web/.env.local` must have `HOUND_DATA=` (empty) and `HOUND_API_URL=http://localhost:8000`.
Health check: open http://localhost:8000/health and expect `"ok": true`.

## The 2-minute click path (script: PITCH.md)
1. Open http://localhost:3000, pick **ohnd-replay-ah** (the DOJ replay).
2. Start the trace. Hops unfold live from the audit log (about 1 second from the snapshot).
3. Click **reveal**: Tether's freezes appear on A-7, A-8, A-9.
4. Exchange hold screen: withdraw to A-1 (`0xcf9b…5027`), expect **HOLD** with evidence. A Binance hot wallet gives **allow**.
5. Packet page (detective audience).
6. Proof panel: 8/8 intermediates, 3/3 seized, A-7 and A-8 green, A-9 amber.
7. Hidden reset button (`POST /demo/reset`) before the next judge.

## When something breaks
| Symptom | Do this |
|---|---|
| Trace never finishes | `curl localhost:8000/health`; if dead, restart `make demo`. If still stuck, play the backup video from the trace step |
| Trace status `partial` | Say so: "one branch couldn't be fetched, and Hound shows it rather than guessing." Both packets open with a PARTIAL TRACE banner that lists the incomplete branches. Keep going |
| Judge gives their own tx hash | Create the case (it traces live with a call budget). It will NOT feed the watchlist (unverified cases never cause holds); say that is by design |
| No internet at all | Both the DOJ replay (committed snapshot) and the live case (local bundle) run with zero network calls |
| Claude API down / no key | Packets fall back to the deterministic template (`source: template`) within about 20 seconds; every number is still verified. Wallet explanations keep their rule text. With a key set, each trace also asks Claude to reword those explanations, so a stalled network slows the trace too: unset the key if the venue network is bad |
| UI shows OFFLINE | `HOUND_DATA=fixture` is set in `web/.env.local`; clear it and rebuild |

## Never on screen
- A live-case address in full (truncate it), and never call a reported wallet "the scammer" (reported, not proven).
- "Sitting there right now" about the DOJ case (it is a replay).
- Any API key, `.env`, or terminal with secrets.
