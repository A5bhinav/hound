# Hound

Hound takes one scam victim's report, follows the stolen USDT to where it sits, finds everyone else still paying the same scam, and gives exchanges a check to hold the next send. Cal Hacks 13.0. Full plan, contracts and task lists: [BRIEF.md](BRIEF.md).

## Run the backend
```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env   # fill in your keys; never commit .env
.venv/bin/uvicorn hound.api:app --reload --port 8000
.venv/bin/python -m pytest -q
```
Python 3.12 or newer.

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
