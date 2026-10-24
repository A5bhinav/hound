# Example fixtures (real data)

Built from real Ethereum USDT transfers (Google BigQuery `crypto_ethereum.token_transfers`, Mar 1 to Jun 26 2024) among the wallets in DOJ case N.D. Ohio 1:25-cv-00386. Every address and tx hash is real.

Use these as stubs until the real modules land (BRIEF 8.4). Known simplifications, so nobody mistakes the fixture for engine output:
- `attributed_amount` equals `amount` here. Real FIFO attribution comes from the engine.
- Edges are all transfers between the 9 known path wallets, including cycles (A-7 → A-6, A-9 → A-6, A-4 → A-1). Real traces will also contain branches to outside wallets.
- `confidence` is 1.0 because these are direct transfers. `other_payers` is empty.
- `label` is null everywhere: DOJ labels are holdout data and must never appear in engine output.
- The 3 endpoints were frozen by Tether in June 2024 (real `AddedBlackList` txs), so `freezable` is false and `replay` is true.
