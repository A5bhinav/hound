# Hound

Hound takes one scam victim's report, follows the stolen USDT to where it sits, finds everyone else still paying the same scam, and gives exchanges a check to hold the next send. Cal Hacks 13.0. Full plan, contracts and task lists: [BRIEF.md](BRIEF.md).

## Run the backend
```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env   # fill in your keys; never commit .env (the API loads it at startup)
cd ..
make dev             # uvicorn with reload on :8000
make test            # pytest
make demo            # HOUND_CACHE_MODE=prefer_cache (AUDIT N5): cache hits served, misses go live; no reload; fails if ANTHROPIC_API_KEY is unset
make schemas-check   # validate examples/*.case.json and *.trace.json against schemas/
```

## Run the web
```bash
cd web
npm ci                         # install dependencies first (otherwise: "next: command not found")
cp .env.example .env.local     # HOUND_DATA= (empty) and HOUND_API_URL=http://localhost:8000
npm run build && npm run start # http://localhost:3000
```

## Check everything (run after any merge, before pushing)
```bash
make e2e    # boots the backend + the production web build like demo day and drives the whole flow;
            # needs `npm ci` done in web/. Ends with "N pass, 0 warn, 0 fail".
cd backend && .venv/bin/python -m hound.chain.preflight   # chain side offline: replay numbers, live bundle, /check
```
Live demo cases are not in git: unzip the private bundle (`hound_cases_live.zip`, from Jinka) inside `data/` so it creates `data/cases_live/`. Without it, `make e2e` and preflight skip the live cases.
The API loads the repo-root `.env` at startup (python-dotenv) and never overrides a variable already set in the environment; it logs which known keys are present, by name only, and warns when `ANTHROPIC_API_KEY` is unset (the writer and classifier then use templates and rules). Python 3.12 or newer. The Makefile uses `backend/.venv`; override with `make test PY=/path/to/python`.

Tracing is async: `POST /cases/{id}/trace` returns `{trace_id, case_id, status: "running"}` at once. Poll `GET /traces/{trace_id}` (or `GET /cases/{id}/trace`) every second until `status` is `done` or `partial` (the full Trace) or `error` (with `error`). While running, the poll body is `{trace_id, case_id, status, started_at, elapsed_s, audit_log_so_far}`, where `audit_log_so_far` is the engine's audit log up to now, so the UI can animate hops live. The POST `trace_id` is a job handle: the finished Trace carries the engine's own `trace_id` plus `job_id` (the handle), so key client state on `job_id`. Fixture data is used only when hound.chain adapters are missing and the case is the curated `doj_replay`; that trace is marked `source: "fixture"`, skips `other_payers` (empty) and is not added to the /check watchlist. Any other chain error ends the job in `error`, never in a fixture trace. A failure in `other_payers` leaves the trace intact with `other_payers: []`. The API bounds the whole job: the engine gets its deadline plus 30 s (an overrun ends the job in `error` with a timeout message), and `other_payers` gets 20 s of its own (an overrun keeps the trace as `partial` with `other_payers: []`). `other_payers` is skipped, with an audit entry, when the trace had chain fetch errors, a seed was not found on chain, or no USDT was traced. Every successful live trace is registered with the watchlist, so /check holds its wallets at once. `GET /cases` returns full Case objects. `POST /cases` assigns `case_id` on the server, rejects `case_id`, `freeze_visibility`, `data_cutoff_block` and `source: "doj_replay"` with 400, and lowercases Ethereum addresses and tx hashes (malformed hex is a 400). It also returns 422 for input the engine would reject: a token other than USDT or ETH (case is normalised), sends on more than one chain, more than 50 sends, a malformed Tron address or tx hash, or a time that is not ISO 8601. An engine `ValueError` reaches the poller with its message. `GET /proof/scoreboard` scores the latest finished replay trace and reports its `trace_source`. On `error`, `error` holds only the exception type and a fixed message; full detail (secrets redacted) is in the server log. The packet always uses the latest successful trace, so a failed re-trace never takes it away. A running job older than the whole-job cap plus 10 s counts as hung and a new POST replaces it. `POST /demo/reset` clears in-memory cases, traces, jobs and cached packets and reloads the curated cases; it needs header `X-Hound-Admin` equal to `HOUND_ADMIN_TOKEN`, or, when no token is set, a request from 127.0.0.1 or ::1 with no tunnel headers (`cf-connecting-ip`, a non-loopback `X-Forwarded-For`). Cases loaded from `data/cases_live/` are redacted for any caller beyond localhost on `GET /cases`, the trace routes and the packet: addresses and tx hashes become prefix 6 + `...` + suffix 4, `story` is dropped and the victim alias is cleared, including the running-job view a repeat `POST /cases/{id}/trace` returns. For a live case the packet beyond localhost carries only its structured fields (`cited`, `source`, `citations_verified`) with `text: null` and `redacted: true`, since the prose is written from the story. The API judges "localhost" by the connecting socket and tunnel headers, so the web server's own SSR fetches count as local: do not tunnel the web app while live cases are loaded unless it forwards `cf-connecting-ip` / `X-Forwarded-For`. Packets written by Claude are cached per (trace_id, audience), so repeat hits never re-call Claude; when `ANTHROPIC_API_KEY` is set but Claude fails and the writer falls back to the template, that template is cached for 60 s so a looping caller retries Claude at most once a minute per key. CORS allows localhost origins plus `HOUND_PUBLIC_ORIGIN` (comma separated).

## Layout
| Path | What | Owner |
|---|---|---|
| `schemas/` | Case + Trace JSON Schemas (the contract between all parts) | Ishaan |
| `examples/` | Real-data fixtures from DOJ case 1:25-cv-00386; use as stubs | Ishaan |
| `backend/hound/chain/` | Chain adapters, cache, labels, freezes | Jinka |
| `backend/hound/watch/` | Other payers, watchlist, check API | Jinka |
| `backend/hound/engine/`, `llm/` | Trace engine, classifier, case writer | Ishaan |
| `backend/hound/proof/`, `intake/` | DOJ scoreboard, backtest, scan, voice + screenshot | CK |
| `web/` | Next.js UI | Aaryan |
| `data/doj/` | Complaint PDF + holdout list | CK |

Every module currently returns a stub built from `examples/` so the API runs end to end today. Replace your stub, keep the function signature (BRIEF 8.4), and validate output with `hound.contracts.validate_trace` / `validate_case`.

## Rules
- The repo is public. Never commit `.env`, keys, or `cache/`.
- Work on your branch, open a PR into `main`; Ishaan merges.
- Fail loudly: log API errors, retries and empty results.
