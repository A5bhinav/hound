# Example fixtures (real data)

- `ohnd_transfers.json`: 414 real Ethereum USDT transfers touching the wallets in DOJ case N.D. Ohio 1:25-cv-00386 (Google BigQuery `crypto_ethereum.token_transfers`, Mar 1 to Jun 26 2024). Served by `hound.fixture_chain` with the BRIEF 8.4 chain interface.
- `ohnd_replay.case.json`: the 20 real USDT transfers into A-1, the first USDT-holding wallet after the victims' swaps (A branch).
- `ohnd_replay.trace.json`: **real engine output** (FIFO) for that case on the fixture chain. Regenerate after engine changes:
  `cd backend && .venv/bin/python -c "..."` (see tests/test_engine.py `run()`).

What the trace shows: from the A-branch victims, FIFO reaches DOJ's A-7 and A-8 blind, through the A-6 consolidation. A-9 is fed mostly by the B branch (`0x447190...`, DOJ's B-3), which these seeds don't include. Labels are null everywhere (holdout). The fixture only contains transfers that touch the 9 known wallets, so outside branches end early; real adapters will go further.
