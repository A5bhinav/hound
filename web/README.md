# Hound web

Next.js 16 UI for Hound (BRIEF §9.4). Talks to the FastAPI backend at `HOUND_API_URL`.

## Run

```
cp .env.example .env.local     # set HOUND_DATA=fixture until the backend is up
npm install
npm run dev                    # http://localhost:3000
```

- `HOUND_API_URL`: backend base URL (default `http://localhost:8000`).
- `HOUND_DATA=fixture`: serve the repo's `examples/` instead of calling the backend. The UI shows an "OFFLINE" flag whenever this is on.

## Routes

| Route | What | Backend |
|---|---|---|
| `/` | Curated case picker | `GET /cases` (server-side) |
| `/cases/[id]` | Case card, trace graph, freeze reveal, other payers | `POST /api/cases/{id}/trace`, then polls `GET /api/traces/{id}` every 1 s |
| `/cases/[id]/packet` | Printable packet, detective or victim (`?audience=victim`) | `GET /cases/{id}/packet` (server-side) |
| `/exchange` | Mock exchange withdrawal screen: hold / warn / allow with evidence | `GET /api/check` |
| `/proof` | DOJ scoreboard, freeze backtest, weekend scan | `GET /proof/scoreboard`, `/proof/backtest`, `/scan/latest` (server-side) |
| `/intake` | Live intake card: case code, QR + short link, "Replay intake" | polls `GET /api/intake/active` every 1 s |
| `/c/[code]` | Victim upload page (one big button, 18px+, "type it instead") | `POST /api/intake/{code}/screenshot` |

Only the `/api/...` routes above are proxied to `HOUND_API_URL` (`next.config.ts`), with a 150 s proxy timeout. Everything else is fetched server-side.

### Intake contract (proposed, CK to confirm)

The intake backend isn't built yet; the UI says so, and "Replay intake" still works. Shapes are in `src/lib/types.ts` (`IntakeSession`, `IntakeUploadResult`):

- `GET /intake/active` → 200 `{case_code, upload_url, status: story|awaiting_upload|validating|validated|needs_retake, story?, victim?, case_id?, message?}`, or 204 when no call is in progress.
- `POST /intake/{case_code}/screenshot` (multipart: `file` image, or `typed` text) → `{status: "validated", case_id}` or `{status: "needs_retake", message}`. The message is shown to the caller as-is, so plain words.
- `upload_url` should point at this app's `/c/{case_code}` through the public tunnel.

Fixture mode reads `../examples/ohnd_replay.case.json` and `ohnd_replay.trace.json` (real engine output) and skips the API. Replays (`method.freeze_visibility: "hidden"`) reveal Tether freezes only after the last hop unfolds (BRIEF §0).

## Against the real backend

```
# repo root; Python 3.11+ works locally (README asks for 3.12)
py -3.11 -m venv .venv && .venv/Scripts/python -m pip install -r backend/requirements.txt
cd backend && ../.venv/Scripts/python -m uvicorn hound.api:app --port 8000
# web/.env.local: HOUND_DATA=  (empty), HOUND_API_URL=http://localhost:8000
```
