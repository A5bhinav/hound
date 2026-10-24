# Demo day runbook (Sun Oct 25)

One laptop runs the demo (Ishaan's). Hard deadline for Devpost is **9:00 AM**; be at the venue by 8 AM. Judging **10:30 AM to 12:30 PM**, all four of us at the table.

## Sun 8 AM checklist
- [ ] `git pull` on main; `make test` is green.
- [ ] Phone hotspot is the primary network. Venue Wi-Fi is the backup.
- [ ] `caffeinate -dims` running (the laptop must not sleep).
- [ ] Focus / Do Not Disturb on. Close Claude Code and anything holding API keys. Browser zoom 125%.
- [ ] Gold case: re-check its balance and freeze status (CK's `getBlackListStatus` + `balanceOf`) and note the time: "checked h:mm AM".
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
| Trace status `partial` | Say so: "one branch couldn't be fetched, and Hound shows it rather than guessing." Keep going |
| Judge gives their own tx hash | Create the case (it traces live with a call budget). It will NOT feed the watchlist (unverified cases never cause holds); say that is by design |
| No internet at all | The replay runs from the committed snapshot with zero network calls. The gold case needs the network for the live balance; show the last "checked h:mm" numbers |
| Claude API down / no key | Packets fall back to the deterministic template (`source: template`); every number is still verified. Nothing else uses Claude on the demo path |
| UI shows OFFLINE | `HOUND_DATA=fixture` is set in `web/.env.local`; clear it and rebuild |

## Never on screen
- A live, unfrozen gold-case address in full (truncate it).
- "Sitting there right now" about the DOJ case (it is a replay).
- Any API key, `.env`, or terminal with secrets.
