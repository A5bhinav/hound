# Hound

Hound takes one scam victim's report, follows the stolen USDT to where it sits, finds everyone else still paying the same scam, and gives exchanges a check to hold the next send. Cal Hacks 13.0. Full plan, contracts and task lists: [BRIEF.md](BRIEF.md).

## Run the backend
```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env   # fill in your keys; never commit .env
cd ..
make dev             # uvicorn with reload on :8000
make test            # pytest
make demo            # HOUND_CACHE_MODE=prefer_cache (AUDIT N5): cache hits served, misses go live; no reload
make schemas-check   # validate examples/*.case.json and *.trace.json against schemas/
```
Python 3.12 or newer. The Makefile uses `backend/.venv`; override with `make test PY=/path/to/python`.

Tracing is async: `POST /cases/{id}/trace` returns `{trace_id, case_id, status: "running"}` at once. Poll `GET /traces/{trace_id}` (or `GET /cases/{id}/trace`) every second until `status` is `done` or `partial` (the full Trace) or `error` (with `error`). While running, the poll body is `{trace_id, case_id, status, started_at, elapsed_s, audit_log_so_far}`, where `audit_log_so_far` is the engine's audit log up to now, so the UI can animate hops live. The POST `trace_id` is a job handle: the finished Trace carries the engine's own `trace_id` plus `job_id` (the handle), so key client state on `job_id`. Fixture data is used only when hound.chain adapters are missing and the case is the curated `doj_replay`; that trace is marked `source: "fixture"`, skips `other_payers` (empty) and is not added to the /check watchlist. Any other chain error ends the job in `error`, never in a fixture trace. A failure in `other_payers` leaves the trace intact with `other_payers: []`. Every successful live trace is registered with the watchlist, so /check holds its wallets at once. `GET /cases` returns full Case objects. `POST /cases` assigns `case_id` on the server, rejects `case_id`, `freeze_visibility`, `data_cutoff_block` and `source: "doj_replay"` with 400, and lowercases Ethereum addresses and tx hashes (malformed hex is a 400). `GET /proof/scoreboard` scores the latest finished replay trace and reports its `trace_source`. On `error`, `error` holds only the exception type and a fixed message; full detail (secrets redacted) is in the server log. The packet always uses the latest successful trace, so a failed re-trace never takes it away. A running job older than the engine deadline plus 30 s counts as hung and a new POST replaces it. `POST /demo/reset` clears in-memory cases, traces and jobs and reloads the curated cases.

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
