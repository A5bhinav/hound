# Hound web

Next.js 16 UI for Hound (BRIEF §9.4). Talks to the FastAPI backend at `HOUND_API_URL`.

## Run

```
cp .env.example .env.local     # set HOUND_DATA=fixture until the backend is up
npm install
npm run dev                    # http://localhost:3000
```

- `HOUND_API_URL`: backend base URL (default `http://localhost:8000`).
- `HOUND_DATA=fixture`: serve `src/fixtures/` instead of calling the backend. The UI shows a "SAMPLE DATA" flag whenever this is on.

## Routes

- `/`: curated case picker (`GET /cases`)
- `/cases/[id]`: case card + trace graph (`POST /cases/{id}/trace`)

`src/fixtures/sample.trace.json` is a UI placeholder (real DOJ addresses, illustrative amounts). Swap for `examples/ohnd_replay.trace.json` when it lands.
