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

- `/`: curated case picker (`GET /cases`, server-side)
- `/cases/[id]`: case card + trace graph. The browser starts the trace with `POST /api/cases/{id}/trace`; if that returns `{trace_id, status: "running"}` (AUDIT N4) it polls `GET /api/traces/{id}` every second and shows the live audit log until the run ends.
- `/api/*` is proxied to `HOUND_API_URL` (`next.config.ts`), with a 150 s proxy timeout for long synchronous traces.

Fixture mode reads `../examples/ohnd_replay.case.json` and `ohnd_replay.trace.json` (real engine output) and skips the API. Replays (`method.freeze_visibility: "hidden"`) reveal Tether freezes only after the last hop unfolds (BRIEF §0).

## Against the real backend

```
# repo root; Python 3.11+ works locally (README asks for 3.12)
py -3.11 -m venv .venv && .venv/Scripts/python -m pip install -r backend/requirements.txt
cd backend && ../.venv/Scripts/python -m uvicorn hound.api:app --port 8000
# web/.env.local: HOUND_DATA=  (empty), HOUND_API_URL=http://localhost:8000
```
