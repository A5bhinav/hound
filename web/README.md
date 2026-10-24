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

- `/`: curated case picker (`GET /cases`)
- `/cases/[id]`: case card + trace graph (`POST /cases/{id}/trace`)

Fixture mode reads `../examples/ohnd_replay.case.json` and `ohnd_replay.trace.json` (real engine output). Replays (`method.freeze_visibility: "hidden"`) reveal Tether freezes only after the last hop unfolds (BRIEF §0).
