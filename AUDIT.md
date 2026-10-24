# Hound technical audit (Fri Oct 23, 9:45 PM)

10 parallel auditors, one per technical dimension, each finding attacked by an adversarial verifier: 96 findings, 95 survived, merged into 26 issues plus 13 from a completeness critic. **BRIEF.md §0 lists what is binding.** This file is the full detail: problem, evidence-backed fix, owner.

Owners: I = Ishaan, J = Jinka, CK = CK, A = Aaryan.

---


I merged 89 verified findings into 26 issues. Where a finding's own fix was rejected during verification, the corrected fix is used here. Owners: **I** = Ishaan, **J** = Jinka, **CK** = CK, **A** = Aaryan.

---

## 1. Issues by severity

### CRITICAL

**1. The replay starts in the wrong place and with the wrong asset. It skips 47% of A.H.'s money and the ETH to USDT swap.**
- **Problem:** A.H. paid ETH to the pass-through 0xd95…4be2cd4. d95 then sent six ETH transfers to A-1 (59.61 ETH), B-1 (30.35 ETH) and C-1 (24.53 ETH), and each of those swapped to USDT (¶69-73). The brief instead seeds one made-up 195,859 USDT send from A-1, so ¶74 can never be reproduced. A-8 is also missing from "Done". The §8.2 example case also contradicts the complaint: it says Coinbase, WhatsApp, 60+ and Feb 2024. The complaint says Crypto.com, a text message, Nov 2023, and no age is given (¶39-41).
- **Fix:**
  - The replay Case is the six d95 → A-1/B-1/C-1 ETH sends from ¶69, with tx hashes from the resolver (issue 15). Token is ETH.
  - Handle ETH only at A-1, B-1 and C-1, in a seed-resolution pass. Run an ETH FIFO at that one address, subtract gas, and join each ETH-out to the USDT-in that shares its tx_hash. That converts the lot at the realised rate and creates an edge with method `swap`.
  - If no USDT-in shares the tx hash, the result is a dead end "unresolved swap" and is shown.
  - Everything after the swap stays USDT-only.
  - Show DOJ's USD valuation next to our swap output, because DOJ valued the ETH at spot price.
  - Build every story field from the complaint, with a `facts_source: "¶n"` on each.
  - "Done" means: from the six sends, the engine reaches A-6, A-7, A-8 and A-9.
  - Keep "USDT start at A-1 reaches A-6" as the Sat 12 PM milestone.
- **Owner:** I (swap resolver, case file), J (txlist and gas fields).
- **Brief:** §8.2, §9.1.2, §10.

**2. The scoreboard compares against numbers we can't reproduce.**
- **Problem:** ¶¶83-85 add up 38 victims and accounts. They mix LIFO, PIFO and FIFO (¶81-82), and only A.H. has published addresses. Line 37 also claims "38 victims traced by FIFO", which is wrong. The run will look like a ~10x miss on stage.
- **Fix:** score in three tiers.
  - **Reach:** non-input DOJ addresses only, which are intermediates A-2..A-6 and B-2..B-4 (x/8) and finals A-7..A-9 (x/3). d95, A-1, B-1 and C-1 are inputs and never count as recall.
  - **Amount:** A.H.'s ¶74 row (A-7 314,657 / A-8 11,954 / A-9 43,071 = 369,683), seeded from all six sends. Colour bands: ≤5% green, 5-20% amber with reasons, >20% red.
  - **Context only:** ¶¶83-85 and the seized amounts, labelled "38 victims/accounts, mixed methods, subpoena data".
  - Also list every endpoint we reach with its amount, so precision shows next to recall.
  - No LIFO mode. It has nothing to score against.
- **Owner:** CK (scoreboard), I (multi-seed run).
- **Brief:** §5.1, §8.4 doj_scoreboard, §9.3.4.

**3. Today's balances and freezes break the replay and leak the answer.**
- **Problem:**
  - balanceOf at latest is 0 for A-7, A-8 and A-9. Tether destroyed the funds at blocks 21196374-5, and destroyBlackFunds emits no Transfer event. So summing Transfers overstates the balance, and the current balance understates it.
  - Etherscan's free eth_call only accepts `latest`, and tokenbalancehistory is a paid PRO endpoint.
  - Frozen wallets can still receive funds, so the replay result changes with the run date.
  - Treating "frozen today" as a stop signal uses the DOJ action itself, so the run isn't blind.
- **Fix:**
  - Every Case gets an `as_of`. For the replay, as_of is 2024-06-05T23:59:59Z, the day A.H. filed with IC3 (¶38). That is after May 30, when the last of her money arrived, and before the Jun 21 freezes. Convert it to a block with getblocknobytime.
  - Transfers are filtered to ≤ as_of.
  - `get_balance(chain, address, token, block)` makes an eth_call to balanceOf (0x70a08231) at a hex block on an archive RPC. Set `ETH_ARCHIVE_RPC_URL` to a free Alchemy or Infura key. The Tenderly public gateway answered past-block calls in our probe.
  - freeze_status is evaluated at as_of, so it returns not frozen during the replay. Then reveal: "Tether froze these 16-20 days later; destroyed and reissued at block 21196374."
  - Stop the simulation at frozen endpoints. Report any later inflows as "received after freeze".
  - Tests: A-7's balance at as_of is ≥ the attributed amount. A-7's status at latest is `destroyed`.
- **Owner:** J (balance at block, archive RPC), I (as_of in engine and Case).
- **Brief:** §4.3, §4.7, §8.2, §8.3, §8.4.

**4. The chain data plan fails under the real limits.**
- **Problem:**
  - Keyless Blockscout is limited per IP. The venue NAT is shared, and this IP is already getting 429s. A keyed Blockscout account gets about 5,000 calls/day.
  - Since Jul 1 2026, the Etherscan free tier returns at most 1,000 rows per request, at 3 calls/s.
  - v1 URLs without chainid are retired.
  - Rate-limit and timeout errors come back as HTTP 200 with `status:"0"` and a string in `result`. The cache would store these as a permanent fake zero. The A-8 silent zero was exactly this.
- **Fix:**
  - Primary source: Etherscan v2, `https://api.etherscan.io/v2/api?chainid=1&module=account&action=tokentx&contractaddress=0xdac17f958d2ee523a2206206994597c13d831ec7&address=X&startblock=S&endblock=E&sort=asc&page=1&offset=1000`. Page by block window: if a page has 1,000 rows, set S to the last row's block, refetch, and dedupe on (hash, logIndex).
  - Each teammate uses their own key (100k/day each). Use a 2.5 calls/s token bucket per key.
  - Secondary source: Blockscout PRO (`api.blockscout.com/v2/api?chain_id=1`, `BLOCKSCOUT_API_KEY`).
  - The archive RPC is used for balances and getBlackListStatus only.
  - `classify_response()` returns `ok`, `empty` or `retryable`. Retryable means non-200, or status 0 with a string other than "No transactions/records found", or an `error`/`Error` key.
  - On retryable: back off 1, 2, 4 then 8 s, fail over to the other source, then raise. Never cache a retryable response. Empty results get a 10-minute TTL.
  - Invariant: if the trace already saw a transfer touching X and get_transfers(X) comes back empty, retry on the second source. If it is still empty, raise.
  - Test: a stubbed 200 "Max rate limit" body raises and caches nothing.
- **Owner:** J.
- **Brief:** §4.2, §7 env, §9.2.2-3.

**5. Voice and SMS intake can't work as specified.**
- **Problem:**
  - A Twilio trial strips `<Stream>`, `<ConversationRelay>` and `<Dial><Sip>`. It only connects verified numbers, caps each call at 10 minutes and gives 75 minutes in total.
  - Trial SMS bodies must be Twilio templates, so no link can be sent. Paid 10DLC or toll-free registration takes days.
  - Cartesia webhook tools need public HTTPS and block private network ranges, so localhost:8000 can't be reached.
  - Phone screenshots of exchange apps usually truncate hashes.
  - Nothing ties the upload to the call.
- **Fix:**
  - Use a Cartesia-provisioned number (the free plan includes 1 number). Build a Managed Agent in the Playground with an Anthropic model from the managed catalog, `noise_suppression: max`, keyterms, and a welcome message under 8 words that opens with the disclosure line.
  - One webhook tool, `POST {PUBLIC_BASE_URL}/intake/voice/story`, with `execution_mode: immediate`. It returns `{case_code, upload_url}` in under 1 s, and the agent reads out the code.
  - Expose the backend with `cloudflared tunnel --url http://localhost:8000`. Start it once and leave it running.
  - No SMS. The case card shows the short URL and a QR code.
  - FastAPI serves the `/c/{code}` upload page through the tunnel, and uploads go to `POST /intake/{case_code}/screenshot`.
  - The asked-for screenshot is the block-explorer tx page.
  - Claude returns JSON with `tx_hash|null`, `to_prefix` and `to_suffix`, and never completes a truncated string.
  - Code then checks the result: regex, an Etherscan receipt lookup, amount within 1%, and prefix and suffix matching. If they match, it overwrites from/to/amount/time with the on-chain values and sets `validated: true`. If not, it returns `needs_retake`.
  - The UI polls `GET /intake/active` every 1 s.
  - Agent minutes cost $0.06/min plus $0.014/min and plan credits don't cover them. Put a card on file or ask at the Cartesia booth.
  - Add a "Replay intake" button that replays a recorded call plus its tool payloads.
- **Owner:** CK (agent, routes, validation), I (tunnel), A (card, upload page, replay button).
- **Brief:** §4.1, §6, §7, §8.4, §8.5, §9.3.7.

**6. "Other payers" counts the launderers' own wallets as payers.**
- **Problem:** Victims pay their own pass-through addresses several hops upstream. The only senders into A-6..A-9 are laundering hops, and the A-1..A-5 cycle adds internal senders on top. Victims send from shared exchange hot wallets, so counting by address collapses dozens of victims into 1. "One hop back" from a hot wallet means nothing and stalls the fetch. In the replay, "38" is DOJ's number, not ours.
- **Fix:**
  - The unit is a **payment**: `{tx_hash, entry_address, source_exchange|null, amount, token, time}`.
  - Entry layer: the trace's depth-0 entry node (d95 in the replay) and any non-trace sender into the first-swap layer (A-1, B-1, C-1). Senders into the first-swap layer are likely other victims' pass-throughs, so cap them at 20.
  - For each entry address, take its inbound payments. Native ETH counts, value ≥100 USDT-equivalent, inside a window that ends at as_of.
  - A sender labelled `exchange_hot` gives a payment row with `source_exchange` set. It is never counted as a distinct payer. An unlabelled EOA sender counts as one payer.
  - Exclude anything that is already a trace node or edge.
  - Never call get_transfers on a labelled address or a high-volume one.
  - UI text: "N payments in from M exchanges into K entry addresses". Show "DOJ identified 38 victims/accounts" in a separate slot.
  - The packet gets one section per exchange, listing the withdrawal tx hashes that went to the cluster.
  - Test: the number comes from `trace.other_payers`, never a constant.
- **Owner:** J.
- **Brief:** §2(4), §3, §4.5, §6 1:20, §8.3, §9.2.8.

### HIGH

**7. The engine algorithm isn't specified tightly enough to be correct.**
- **Problem:**
  - A per-node or DFS FIFO breaks on the A-1↔A-2 cycles and on the B-4→C-1 flows.
  - Order inside a block is undefined: tokentx has no logIndex.
  - FIFO needs each in-scope address's full history up to as_of.
  - A count cap on branches throws attributed value away, and sub-100 slivers vanish without anyone noticing.
  - Floats drift as lots get split.
  - A router, pool or hot wallet that enters scope stalls the trace.
  - There is no call budget and no time cap.
- **Fix** (in `engine/fifo.py`):
  - Scope S starts as the seed addresses. Fetch the full history ≤ as_of for S. Merge everything that touches S into one list, sorted by (block, tx_index, log_index) and deduped.
  - Replay that list through per-address lot deques `(seed_id, amount)`. The opening balance and untainted inflows are lots with seed_id None.
  - Add new tainted recipients that pass the gate. Repeat until nothing new is added or max_hops is reached.
  - depth = shortest graph distance from the seed.
  - Gate, in order: label DB → exchange endpoint. is_contract and a same-tx swap counterparty → `swap`, never scoped. Other contract → dead_end service/bridge. High-volume probe (first page with sort=desc is full and spans less than a day) → endpoint `high_volume`.
  - Only plain EOAs are added to scope.
  - Caps only decide which addresses get expanded. Inflows are always queued.
  - Follow every tainted outflow ≥ min_amount. Beyond the top N, money goes to one `capped` endpoint per node. Dust goes to one `dust` endpoint per node.
  - Store amounts as integer base units and serialise with round-half-even to 6 dp.
  - Add `attributed_by_seed` on edges and endpoints, and a top-level `seeds` list.
  - Add `max_api_calls=400` (endpoint reason `budget`) and `HOUND_TRACE_DEADLINE_S=25` (reason `time_cap`, with `status: partial`).
  - An outflow that would take a queue below zero raises ReconciliationError.
  - Tests: conservation per seed down to the micro-unit (endpoints + capped + dust + residual + tether_destroyed = seed). Two replays must produce byte-identical JSON.
- **Owner:** I, with J for tx_index/log_index and the probe.
- **Brief:** §4.3, §8.1, §8.3.

**8. An LLM sits inside the "deterministic" stop rule, and confidence has no formula.**
- **Problem:**
  - "Classified deposit/hot wallet" stops the trace on Claude's output. On Opus 5.5 you can't set temperature, so runs aren't repeatable.
  - Per-victim platform deposit addresses look exactly like exchange deposits, so the trace would stop at hop 1.
  - DOJ's own chart captions A-2 "Cross-chain Swap", so a bridge rule could stop the replay at hop 2.
  - Holds threshold on a confidence number nobody defined.
- **Fix:**
  - Exchange kinds come only from labels, or from one deterministic sweep check: ≥90% of inflow goes to a labelled exchange hot wallet within 24 h, or gas was funded by a labelled exchange "Deposit Funder".
  - kind=bridge only when the counterparty is a labelled bridge contract and no same-chain USDT moves on within 24 h.
  - `classify()` runs after the trace, on features only (no address, labels, token names or freeze state). It may return pass_through, consolidation, holding, service or unknown, plus reasons. It is shown as an opinion and never stops or prunes anything.
  - Confidence: `edge = base(method) × completeness`. base: direct 1.0, consolidation 0.9, swap 0.9, peel 0.85, bridge_match 0.6. Completeness is 1.0, or 0.5 if history is incomplete. Path confidence is the product along the path. Publish the table in `method.confidence_model`.
  - Classifier eval: 30 addresses (10 seeded hot wallets, 10 OLI deposit-address tags, 10 non-holdout Tether-frozen). Print "x/30, scam-called-exchange = k".
  - Regression tests: A-2-like behaviour is not bridge. A forward trace never stops at d95.
- **Owner:** I, with J for the sweep check and CK for the eval list.
- **Brief:** §4.3, §4.4(a), §8.3, §9.1.3.

**9. Freeze data: the address isn't an indexed topic, and unfreezes and burns are ignored.**
- **Problem:** On Ethereum USDT, AddedBlackList, RemovedBlackList and DestroyedBlackFunds all carry the address in `data`, not as topic1. Filtering by topic1 returns empty for every address, so everything looks "not frozen".
- **Fix:**
  - One-time dump of all three events (~3,180 + 347 + 1,296) via block-chunked getLogs into `data/freezes_eth.json` (public data, commit it).
  - Keyed by address: list of `{event, block, tx, amount}`.
  - `freeze_status(chain, address, as_of)` becomes a local lookup returning `{status: frozen|unfrozen|destroyed|none, frozen_at, freeze_tx, destroyed_amount, destroyed_tx}`.
  - Refresh the tail every 10 minutes. For live cases, cross-check with getBlackListStatus (0x59bf1abe) at latest.
  - Topics: RemovedBlackList `0xd7e9ec6e6ecd65492dce6bf513cd6867560d49544421d0783ddf06e76c24470c`, DestroyedBlackFunds `0x61e6e66b0d6339b2980aecc6ccc0039736791f0ccde9ed512e789a7fbdd698c6`.
  - Test: A-7 frozen at block 20140818, destroyed 4,340,000 at block 21196374.
- **Owner:** J.
- **Brief:** §8.1, §8.3, §8.4, §9.2.4.

**10. The cache has no offline mode, no shared snapshot, and its key would leak API keys.**
- **Fix:**
  - `HOUND_CACHE_MODE=live|record|readonly`. In readonly mode a miss raises `CacheMiss` and the UI shows it.
  - Strip `apikey`, `api_key` and `token` from params before hashing. Test that no file in the cache contains any value from .env.
  - TTL: immutable if endblock < head−64. Anything touching head, balance at latest, or the freeze tail gets 5 minutes.
  - `make warm` runs every curated Case, the scoreboard, the backtest and the scan in record mode, crawling from the Cases and never from the holdout list. Commit the result to `data/fixtures/cache/*.json.gz` (public chain data, under 50 MB per file).
  - The LLM cache is keyed on `sha256(model + PROMPT_VERSION + input)`.
  - Only J's machine warms the cache. Freeze the snapshot at Sat 10 PM. The demo and all tests run in readonly mode.
- **Owner:** J (chain), I (LLM).
- **Brief:** §4.2, §7, §9.2.3.

**11. The Transfer contract can't support swaps, ordering, poisoning filters or time windows.**
- **Fix:**
  - Transfer = `{chain, tx_hash, log_index, tx_index, block, time, from, to, token, contract, amount_base, decimals, kind: native|internal|erc20}`.
  - Merge txlist (`isError=="0"`, value>0), txlistinternal and tokentx.
  - Always drop value 0 and from==to. Match on the contract address, never the symbol. Count each drop type in stats.
  - Convert ISO times to blocks with getblocknobytime and cache the result forever.
  - Add `swaps(address)`: group rows by tx_hash where native goes out and USDT comes in.
  - Tests: the A-1 swap shows as one ETH-out/USDT-in pair. A 0-value sender is never a payer.
- **Owner:** J.
- **Brief:** §8.1, §8.4.

**12. The label sources don't do what the brief assumes.**
- **Problem:**
  - dawsbot has no Binance hot wallets, and its 5,000 Binance deposits are labelled 'bilaxy'. **Don't use dawsbot.** This overrides the finding that suggested merging it.
  - brianleect hasn't been updated since Oct 2023.
  - Etherscan tags need Pro Plus.
  - OFAC splits each chain's addresses across asset lists and uses mixed case.
  - Tron has no free label source.
  - Free-text "X: Binance Deposit" names point at the wrong exchange.
- **Fix:** labels.py, in priority order:
  1. Blockscout metadata service, `metadata.services.blockscout.com/api/v1/metadata?addresses=a,b&chainId=1`, batched and cached. Accept generic `exchange` OR `hot-wallet` (Crypto.com has hot-wallet only), plus `deposit-address`. Take the name from tagType name/protocol. Lowercase keys. Strip the `blocked` tag, because freeze status comes only from freeze_status at as_of.
  2. brianleect with a slug allowlist.
  3. `data/labels/seed.json`: about 20 hand-checked hot wallets (Crypto.com, Coinbase, Kraken, Binance).
  4. `data/infra_allowlist.json`: USDT contract, Tether Treasury, WETH, Uniswap V2/V3/Universal routers, 1inch, 0x proxy, canonical bridges. These are never held or expanded.
  5. OFAC from the 0xB10C lists. Ethereum = lowercase(ETH ∪ USDT 0x). Tron = TRX ∪ USDT T…. A hit gives kind `sanctioned`, check = hold, and the trace continues.
  - "Deposit Funder" → kind service, used only as a feature.
  - Behaviour guard: >50k txs or >1k counterparties → kind service.
  - Record `label_source` on every label and credit it on the packet.
  - Tron: `TRONSCAN_API_KEY` plus `seed_tron.json`. Until those exist, Tron nodes show "unlabelled", never exchange.
- **Owner:** J.
- **Brief:** §8.3, §8.4, §9.2.5, §9.2.7.

**13. The check API has no thresholds, can be gamed, fails open, and its demo holds a meaningless address.**
- **Fix:**
  - **HOLD:** the recipient is Tether-frozen, OR it is a trace node of kind entry, intermediate, consolidation or holding, with path confidence ≥0.8 and attributed ≥100 USDT, in a case whose send was verified on chain. The case itself counts as the report.
  - **WARN:** trace nodes at 0.5-0.8. Entry addresses from other_payers ("pays into scam"). Chainabuse-only addresses. Last victim inflow older than 30 days.
  - **ALLOW:** everything else, worded "no Hound data". Exchanges, services, infrastructure and sanctioned-exempt kinds always get allow plus a note.
  - Reports alone never hold. "Independent" means distinct reporter and distinct source tx.
  - WARN-only addresses are never exported to the packet or to Chainabuse.
  - `build_watchlist()` writes `cache/watchlist.json` after each trace. check() is a pure in-memory lookup.
  - Normalise input: regex plus lowercase for Ethereum, base58check for Tron. Invalid input returns 400, never allow. A 1.5 s timeout shows amber "not checked".
  - Typed evidence: `{watchlist_version, rule_fired, case_ids, label, path[≤4 hops], victim_inflow_usdt, frozen, chainabuse{report_count,latest_at}, expires_at, disclaimer:"reported, not proven"}`.
  - Commit `examples/check.{hold,warn,allow}.json`.
  - Demo: hold on d95, resolved by the issue 15 resolver, else A-1. Say "A.H.'s next $300K 'credit score' payment (¶44) would have been held here." The live gold-case first hop is the other hold example.
  - Tests: allow on a Binance hot wallet, the Universal Router and the victim's own address. A planted 0-value poison and a fake-USDT transfer both get allow. Two fake reports against a hot wallet still get allow.
- **Owner:** J, with CK for report dedupe and A for the hold screen.
- **Brief:** §4.5, §4.6, §8.4, §8.5, §9.2.9, §12.

**14. Holdout leak paths beyond the label DB.**
- **Problem:** The examples stub holds DOJ addresses. The brief, full addresses included, goes into every agent. Pre-warming "the DOJ path" steers which branches survive a 429. Raw addresses sent to Claude can be recognised from training data. Caps get tuned while the answer is known.
- **Fix:**
  - `tests/test_holdout.py` greps `backend/hound/**` and the engine fixtures for every holdout address and prefix…suffix regex. It allowlists only the replay Case sends (d95, A-1, B-1, C-1) and excludes `proof/` and `data/doj/`. It asserts the engine never imports proof or reads data/doj.
  - `examples/ohnd_replay.trace.json` gets `"source":"hand_built"` and is a UI fixture only. The scoreboard refuses hand_built traces.
  - Commit the method params and show the git SHA on the proof panel.
  - Fetch failures that survive retries go to `stats.fetch_errors`. The scoreboard then shows "incomplete" rather than crashing.
  - Prepare an answer to "how did you get the start address?": "DOJ printed it in ¶69, truncated; we resolved it; the engine got nothing else."
- **Owner:** CK (test, scoreboard), I (stub removal, classify inputs, params SHA).
- **Brief:** §5.1, §8.4, §9.1, §9.3.

**15. The holdout list is corrupted by OCR, and there's no plan to resolve the truncated addresses.**
- **Problem:** The .txt version has `eb691`/`fd1`. The PDF reads `0x4471…eb6911a` (B-3) and `0x28b8…fd17376` (B-4), which is why the kill test missed them. You can't search the chain by address prefix.
- **Fix:**
  - CK builds `holdout.json` by hand from the PDF images, p.17-19: 15 entries (d95, A-1..A-9, B-1..B-4, C-1) with the longest prefix, the suffix, full|null and source_page.
  - `proof/resolve_ohnd.py`, with Etherscan as source:
    1. A-1's inbound ETH: 33.00 (~May 17) and 26.61 (~May 21) from a sender matching d95…4be2cd4.
    2. d95's outbound (txlist + txlistinternal): 15.08/15.27 ETH → B-1 `e799…c2d6ad0`; 16.14/8.39 ETH → C-1 `a327…6f4dbb8`.
    3. B-1/C-1 tokentx: B-2 matched by 65,576.697684 and 49,545.16207; then B-3 and B-4.
  - Match on amount ±0.5% and date ±2 days. Fail loudly on 0 or >1 matches.
  - Record the matching tx_hash per address in `data/doj/resolved.json`. It is for scoring only and the engine never reads it.
  - Unit test: 15 entries, and A-6 marked resolved.
- **Owner:** CK.
- **Brief:** §5.1 line 47, §9.3.3.

**16. The citation test checks the wrong things and would break the build on good packets.**
- **Problem:** True facts in the packet (38 victims, DOJ totals, case fields, aggregates, contacts) are not in the Trace. Matching numbers in free prose is fragile. Fake addresses and dates slip through. A build-time test can't guarantee anything about a packet written live. Untrusted text can steer the prose. Nothing stops "your money will be recovered".
- **Fix:**
  - `llm/facts.py` builds a facts dict: `trace.*`, `case.*`, `derived.*` (computed by code), `doj.*` (replay only), `const.*` (contacts, windows).
  - Claude returns a template with `{{path|fmt}}` placeholders, via an output_config JSON schema. Code renders it with fixed formatters.
  - `writer.validate(template, facts)` runs on every generation. It fails on:
    - an unknown path
    - a digit, a 0x/T address or a month name outside a placeholder. Allowlist: IC3, A-\d, B-\d, C-\d, ERC-20, TRC-20, 1:25-cv-00386, ¶
    - number words (one…billion, dozen, several)
    - banned phrases: recover guaranteed, "will be returned", "get your money back", "victims" for live payers, "scammer"/"criminal" as a noun for an address
    - URLs or phones not in const.contacts
  - On failure: retry once, then fall back to a deterministic template.
  - The footer is written by code: "reported, not proven"; "Hound never charges or asks for keys; anyone offering paid recovery is a scam"; "citations verified N/N".
  - Free text goes in `<untrusted_story>` tags and is never citable.
  - Tests use recorded good and bad fixtures and make no network calls.
- **Owner:** I, with CK for the phrase list.
- **Brief:** §4.4(b), §8.4, §9.1.4, §12.

**17. Live cases, the watchlist and Chainabuse data would be published, and the Chainabuse contract and quota handling are wrong.**
- **Problem:**
  - The repo is public, and §7 commits `data/cases/`, which contradicts §12.
  - Live unfrozen addresses in the video would tip off the launderers.
  - The Chainabuse API is proprietary. ReportPayload has no tx hash, report_count or confidence. The orderByDirection docs are backwards.
  - The 10 calls/month quota has no spend guard, and nothing bans per-address calls.
- **Fix:**
  - `data/cases_live/`, `cache/`, `watchlist*.json` and `scan_*.json` are gitignored. Commit only the DOJ replay, labels, examples and fixtures.
  - Truncate live addresses everywhere public. Never render description, accusedScammers or ips. Link to chainabuse.com/report/<id>.
  - Chainabuse: one key. No call happens without `HOUND_CHAINABUSE_SPEND=1`, and every call is logged in `cache/chainabuse/ledger.json`.
  - Plan ≤10 calls with `category=PIGBUTCHERING|FAKE_RETURNS|OTHER_INVESTMENT_SCAM`. Never use `address=`. Find gold-case candidates through the website by hand.
  - Contract: `{report_id, address, chain, category, reported_at, checked, trusted, claimed_losses[]}`. report_count is computed by grouping on address.
  - File a real Chainabuse report for the gold case on Saturday and say "reported at <time>". If it isn't filed, the most we can say is "ready to file".
  - Before the pitch, re-check getBlackListStatus and balanceOf, and show "checked h:mm AM".
- **Owner:** CK, with A for redaction.
- **Brief:** §5.3, §7, §8.4, §9.3.6, §12.

**18. The Sat 12 PM Must is one long serial chain, and there is a single integrator.**
- **Fix:**
  - Tonight, J ships cache.py with record mode in the first hour, plus a recording run over the KILL_TEST §2 addresses. I builds the engine against those fixtures.
  - Each package exposes its own APIRouter, and api.py only calls include_router.
  - Owners self-merge PRs that only touch their own directories once `make test` passes. I reviews models.py, api.py, the engine and schemas.
  - Merge windows at 12, 3, 6 and 9 (AM and PM).
  - `backend/hound/models.py` (Pydantic v2) is the single source of types. `make schemas` exports the JSON Schema. The web generates its types with openapi-typescript. Commit an example per route, and `HOUND_STUB=1` serves them.
  - Tooling: uv with uv.lock, package-lock.json, and a Makefile with dev/test/warm/demo/schemas. No CI.
  - `next.config` rewrites `/api/:path*` → HOUND_API_URL. Symlink `web/.env.local` to the root .env. Add CORSMiddleware as a fallback.
  - Gates: Sat 12 PM, if the engine doesn't reach A-6/A-7, scope freezes to the replay, check and packet. Sat 6 PM, if voice doesn't take a real call end to end, drop the Cartesia track.
  - Cut order: Tron, weekend scan, live call, backward expansion.
  - Pitch Q&A prep moves to CK.
- **Owner:** I (gates, models, skeleton), all.
- **Brief:** §7, §8, §9, §10.

**19. There is no demo-ops plan, and the script runs 3 minutes against a recommended 2.**
- **Problem:** The guide recommends a 2-minute pitch with a live demo, and Cartesia asks for 2 minutes, demo first. Tables are shared by 2-3 teams and the hall is loud.
- **Fix:**
  - One demo laptop, Ishaan's, running `make demo`: readonly cache, recorded LLM outputs, `next build && next start`, and the tunnel only for voice.
  - A phone hotspot is the primary network.
  - Fixed case_ids, plus `POST /demo/reset` behind a hidden button.
  - The 2-minute demo-first version is the default.
  - The recorded call clip is the default. Do the live call when Cartesia judges visit.
  - Keep the full video on the desktop as a last resort. Bring a charger and a power strip.
  - Don't host the backend.
- **Owner:** I (make demo, reset), A (cut, video).
- **Brief:** §6, §10.

**20. The gold case is a low-odds bet on Ethereum, and it needs an engine that doesn't exist yet.**
- **Fix:**
  - Tonight, CK browses chainabuse.com by hand and puts candidates in `data/cases_live/candidates.txt`.
  - A script filters with no engine needed: no exchange label, <2,000 lifetime transfers, getBlackListStatus 0, USDT balanceOf ≥ $5K, and a balance ≥ the claimed loss either at the reported address or within 2 hops. Rank by balance.
  - Shortlist 3 by midnight, and J warms them.
  - Tron candidates count only if tron.py works by 10 AM.
  - Keep the single Sat 10 AM gate. If nothing qualifies, fall back to "landed at exchange X".
- **Owner:** CK.
- **Brief:** §9.3.1.

**21. The prize stack names tracks wrongly and misses the two best fits.**
- **Fix:**
  - Correct names: Most Technically Complex Hack; Best People-First Hack.
  - Add Anthropic (named community, real problem, works, "where Claude could go wrong") and the Microsoft Customer Impact Award.
  - Re-check Armadin's criteria (still "Coming soon") on Sat morning.
  - Coinbase stays dropped.
  - Cartesia stays only if voice ships.
- **Owner:** A.
- **Brief:** §11, §9.4.8.

**22. The brief contains factual errors that agents will copy.**
- **Problem:** Line 37 says "38 victims traced by FIFO". Line 46 says "no bridges", but DOJ's chart captions A-2 "Cross-chain Swap". Line 47's path skips A-6, and its missing list holds OCR errors. §4.7's freeze rule would mark A-9 as unfreezable if applied to aggregate totals (795,255 traced vs 577,578 seized).
- **Fix:** see the exact brief edits in §2.
- **Owner:** I.
- **Brief:** §4.7, §5.1.

### MEDIUM

**23. The backtest metric is mislabelled, and its population is mixed.**
- **Fix:**
  - Name the metric `detection_lag_hours` (median and p90): first inflow → AddedBlackList.
  - Add `escape_share` = USDT out before freeze / USDT in before freeze.
  - Population: 2025 Ethereum AddedBlackList events from the freeze dump (~657), `random.seed(13)`. Skip addresses with >5,000 transfers and report `n_skipped`. Label OFAC hits 'sanctions' and exclude them from the headline. Everything else is "LE/scam/hack, not separated".
  - Balance at freeze = archive balanceOf at freeze_block−1.
  - Run it once as a batch job that writes `data/proof/backtest.json`.
  - Cite BlockSec's 54% as their number. Don't present it as our reproduction.
  - Screen text: "Tether froze a median X hours after the first stolen dollar arrived; by then about Y% had already left."
- **Owner:** CK.
- **Brief:** §5.2, §8.4, §9.3.5.

**24. The weekend scan headline will be inflated.**
- **Fix:**
  - Apply the watchlist exclusions.
  - Drop anything with >2,000 lifetime transfers or >50 distinct senders in 7 days.
  - Category must be one of the three investment-scam enums.
  - Each address contributes min(balance, the sum of claimed losses). Show the capped number on stage.
  - Return per-address rows with an "as of" timestamp.
- **Owner:** CK.
- **Brief:** §5.3, §8.4.

**25. The Tron adapter isn't specified.**
- **Fix:**
  - Transfers: `/v1/accounts/{b58}/transactions/trc20?contract_address=TR7N…&only_confirmed=true&limit=200&order_by=block_timestamp,asc&min_timestamp=…`. Follow meta.fingerprint and keep the other params identical between pages. Keep only `type=="Transfer"`.
  - Freezes: dump the three events from `/v1/contracts/TR7N…/events` into `data/freezes_tron.json`.
  - `_user` is 0x hex, so convert it with `hex_to_base58` (0x41 prefix plus a double-sha256 checksum) and unit-test it on a known pair.
  - Past balance = sum of transfers minus DestroyedBlackFunds.
  - Send the `TRON-PRO-API-KEY` header and cap at 10 rps.
- **Owner:** J.
- **Brief:** §9.2.7.

**26. Anthropic models, credits and customer evidence are unplanned.**
- **Fix:**
  - classify uses `claude-haiku-4-5` with structured output, max_tokens 300, concurrency 4 and `max_retries=5`.
  - write_case uses `claude-opus-5-5` with effort low, structured output, streaming and `fallbacks:"default"`. Check stop_reason before parsing.
  - No temperature, no prefill, no forced tool_choice. Each returns a 400 on 5.5 models.
  - Pre-generate packets for every curated case.
  - Claim event credits tonight. The demo key lives only in the demo backend's env. Never source .env into a shell, because Claude Code will then use that key.
  - CK spends 30-60 minutes at the Coinbase booth on Saturday asking what evidence they need before holding a withdrawal. Collect 2-3 quotes, attributed by role.
- **Owner:** I, CK.
- **Brief:** §7, §9.1, §9.3.

---

## 2. Exact brief edits

**§4.1, line 27.** Replace:
`The victim calls (Twilio + Cartesia voice) and tells the story: scam app name, platform, dates, amounts, which exchange they sent from. Nobody reads a 64-character hash over the phone, so the agent texts a link; the victim uploads a screenshot of the send screen; Claude reads it and extracts the tx hash and addresses. Output: a **Case** (§8.2).`
With:
`The victim calls a Cartesia number. A Cartesia Managed Agent collects the story: scam app, platform, dates, amounts, and the exchange they sent from. A webhook tool posts the story to our backend through a public tunnel. The backend returns a short case code, and the agent reads it out. The victim opens the short link or scans the QR code. They upload a screenshot of the block-explorer page for their send. Claude reads it and never completes a truncated string. Code then checks the hash on chain and keeps the on-chain values. No SMS. No Twilio. Output: a **Case** (§8.2).`

**§4.2, line 28.** Replace:
`Ethereum first (Blockscout API, free, no key; our answer-key case is on Ethereum), Tron second (TronGrid). Disk cache for every response, back-off on HTTP 429, **log every empty result** (the kill test got one silent zero that a retry fixed).`
With:
`Ethereum first. Primary source is Etherscan v2 with one free key per teammate (1,000 rows per call, 3 calls/s). Page by block window, never by page number. Secondary source is Blockscout PRO with a free key. Balances and freeze checks use an archive RPC at a given block. Tron second (TronGrid). Errors often arrive as HTTP 200 with status "0". classify_response() catches them. Never cache a retryable response. Empty results get a 10 minute TTL. A cache snapshot is committed. The demo and tests run in readonly mode.`

**§4.3, line 29.** Replace from `Forward from the victim's send` to the end of the line with:
`Forward from the victim's send, using **FIFO** (DOJ's method for its named victims). It is one global time-ordered replay over a growing set of addresses, sorted by (block, tx_index, log_index). That handles cycles. Every Case has an as_of time. Transfers, balances and freeze status are read at as_of. ETH is handled only at swap addresses, by a same-tx join to the USDT that comes back. Amounts are integers in base units. Caps decide which addresses get expanded, never which inflows are counted. Capped and dust money go to visible endpoints. Stops are deterministic: labelled exchange or a proven sweep to one, a holding or frozen wallet at as_of, a contract, a high-volume address, a dead end, dust, max hops, call budget or time cap. Claude never decides a stop. Confidence uses the fixed table in method.confidence_model. Output: a **Trace** (§8.3).`

**§4.4, line 30.** Replace:
`(a) **Address classifier**: behaviour features in → kind + reasons + confidence. (b) **Case writer**: plain English for the victim, formal for the detective; it may **only cite fields from the Trace object**, and a test fails the build if any number in the packet isn't in the Trace.`
With:
`(a) **Address explainer**: after the trace, it takes code-computed features (no address, no labels, no freeze state) and returns an opinion with reasons. It is shown in the UI and never stops the trace. It is scored on a 30-address eval. (b) **Case writer**: it returns a template with placeholders. Code fills them from a facts dict (trace, case, derived, doj, const). A validator runs on every generation and rejects raw numbers, addresses, dates, number words and unsafe phrases. It retries once, then falls back to a fixed template.`

**§4.5, line 31.** Replace from `From the scam wallets found` to the end of the line with:
`Victims pay their own pass-through address, and victims on exchanges send from shared hot wallets. So count payments, not sender addresses. Look at the trace's entry layer: the entry node, plus senders into the first swap addresses that are not trace nodes. List each inbound payment with its tx hash, amount and source exchange, inside a window ending at as_of. Exclude cluster-internal moves. Say "N payments from M exchanges into K entry addresses". Show DOJ's 38 victims and accounts beside it, in a separate slot. **Check rules:** HOLD if the recipient is Tether-frozen, or it is a trace node with path confidence 0.8 or more and at least 100 USDT attributed, from an on-chain-verified send. WARN for entry addresses from other payers, Chainabuse-only addresses, confidence 0.5 to 0.8, or nothing new for 30 days. Reports alone never hold. Exchanges, services and infrastructure always get allow with a note. Allow means "no Hound data".`

**§4.7, line 33.** Replace:
`Freeze requests use "address balance ≥ victim's inflow", never a diluted share.`
With:
`Freeze requests are per victim. They ask for min(balance at as_of, this victim's inflow) and flag any address where the balance is below the inflow. The packet keeps three columns apart: victim funds traced, balance at as_of, and seized (DOJ).`

**§5.1, line 37.** Replace:
`38 victims traced by FIFO into 3 Ethereum USDT wallets.`
With:
`38 victims and victim accounts (¶ 66) traced into 3 Ethereum USDT wallets, using mixed methods. DOJ published one victim's path, A.H.'s. We replay it blind.`

**§5.1, line 45.** Replace:
`**Scoreboard metric (CK):** intermediates reached (x/11), A-6 reached, finals reached (x/3), per-wallet totals vs ¶¶ 83-85. Partial credit shown honestly.`
With:
`**Scoreboard (CK), three tiers.** Reach: intermediates we were not given (A-2 to A-6, B-2 to B-4, x/8) and finals (x/3). Amount: A.H.'s ¶ 74 row (A-7 314,657, A-8 11,954, A-9 43,071), seeded from her six ETH sends. Green is within 5%, amber 5 to 20% with reasons, red over 20%. Our swap output is shown next to DOJ's USD values. Context only: the ¶¶ 83-85 totals and the seized amounts. Every endpoint we reach is listed too, so precision shows next to recall.`

**§5.1, line 46.** Replace:
`it says Tron and cross-chain swaps; the complaint says Ethereum, no bridges.`
With:
`it says Tron. Every hop DOJ charted is Ethereum USDT. DOJ's chart captions A-2 "Cross-chain Swap", so a bridge stop only fires on a labelled bridge contract with no same-chain USDT moving on within 24 hours.`

**§5.1, line 47.** Replace from `→ \`0x78366b2f…\`` through the end of the line with:
`then the A-1 to A-5 loop, then A-3, then A-6, then A-7 / A-8 / A-9. All Ethereum USDT after the swap. Also found: 0x78366b2f6c5321ac30629c078120385ae2da1a06, 0x9eb0c71e79066552bdd05a69fc4dcac075db5e1f, 0xdf6fa72c71577c3a3209db202d4815021f0ed53f, 0x07fbb418aac62abc4ca3e7ee8ccf8ce7693e9d53, and A-6 0x58e99d9413bb6ce05748a84f76e5fff4bb2d0dcb. Still missing, read from the PDF images and not the .txt: d95…4be2cd4, e799…c2d6ad0 (B-1), a327…6f4dbb8 (C-1), 212a…4d9c794 (B-2), 4471…eb6911a (B-3), 28b8…fd17376 (B-4). proof/resolve_ohnd.py finds them.`

**§5.1, line 48.** Replace:
`DOJ's per-wallet totals to score against (complaint ¶¶ 83-85):`
With:
`DOJ's all-victim totals, for context only and never scored (¶¶ 83-85):`

**§5.1, after line 49, add:**
`- **Replay as_of = 2024-06-05** (A.H.'s IC3 report, ¶ 38). Freezes happened later, so the engine sees them as not frozen. The UI then reveals: "Tether froze these 16 to 20 days later." The method params are committed and the git SHA is shown on the proof panel. The holdout test greps the engine code and fixtures. It allows only the replay Case sends.`

**§5.2, line 51.** Replace:
`For a sample of frozen addresses, measure how long the money sat there before Tether froze it. "The window" becomes our own measured number.`
With:
`For 2025 Ethereum freezes (sanctions excluded), measure detection lag (first inflow to freeze, median and p90) and escape share (USDT out before the freeze divided by USDT in). Label the population on screen. Run it once as a batch job.`

**§5.3, line 52.** Append:
`Filters: no exchange or service labels, no high-volume addresses, investment-scam categories only. Each address counts at most its claimed loss. Re-checked live before the pitch. Live addresses are truncated in anything public.`

**§6, line 56.** Replace:
`0:20 The call: story by phone, screenshot by text, the case card fills in.`
With:
`0:20 The call (recorded clip by default, live for Cartesia judges). The agent reads out a case code, the explorer screenshot is uploaded, the case card fills in.`

**§6, line 58.** Replace:
`(real count; DOJ replay = the complaint's 38 victims)`
With:
`(Hound's computed payment count, with DOJ's 38 shown beside it as a benchmark)`

**§6, line 59.** Replace:
`1:45 An exchange withdrawal gets held, with evidence.`
With:
`1:45 A withdrawal to the gold case's first hop is held. On the replay: "A.H.'s next $300K payment to d95 would have been held here."`

**§6, after line 62, add:**
`The 2-minute demo-first cut is the default: trace, hold, packet, proof, ask. The $4.4B line closes. One demo laptop runs make demo (readonly cache), on a phone hotspot. POST /demo/reset sits behind a hidden button.`

**§7, line 65.** Append:
`Backend: uv with a committed uv.lock. Web: a committed package-lock.json. A Makefile has dev, test, warm, demo and schemas. backend/hound/models.py (Pydantic) is the single source of types. The web proxies /api to the backend through next.config rewrites.`

**§7, line 82.** Replace:
`data/cases/         curated demo cases (committed)`
With:
`data/cases/         DOJ replay case only (committed)
    data/cases_live/    gold case, scan rows (gitignored)
    data/fixtures/cache/ committed cache snapshot (public chain data)
    data/freezes_eth.json, data/labels/ (committed)`

**§7, line 85.** Replace:
`**Ishaan merges**.`
With:
`Owners self-merge PRs that touch only their own directories, after make test passes. Ishaan reviews changes to models.py, api.py, the engine and the schemas. Merge windows at 12, 3, 6 and 9 (AM and PM).`

**§7, line 87.** Replace the whole env list with:
`ANTHROPIC_API_KEY, ETHERSCAN_API_KEY (primary, one per teammate), BLOCKSCOUT_API_KEY, ETH_ARCHIVE_RPC_URL, TRONGRID_API_KEY, TRONSCAN_API_KEY, CHAINABUSE_API_KEY, HOUND_CHAINABUSE_SPEND, CARTESIA_API_KEY, CARTESIA_AGENT_ID, PUBLIC_BASE_URL, HOUND_CACHE_MODE (live|record|readonly), HOUND_STUB, HOUND_TRACE_DEADLINE_S, HOUND_API_URL. Never source .env into a shell.`

**§8.1, line 95.** Replace:
`Amounts are **decimal numbers in whole token units** (USDT has 6 decimals on-chain; adapters convert).`
With:
`Inside the engine, amounts are integers in base units. They become decimals with 6 dp (round half even) only in JSON output.`

**§8.1, line 96.** Append:
`The address is in the log data, not topic1. Also track RemovedBlackList 0xd7e9ec6e6ecd65492dce6bf513cd6867560d49544421d0783ddf06e76c24470c and DestroyedBlackFunds 0x61e6e66b0d6339b2980aecc6ccc0039736791f0ccde9ed512e789a7fbdd698c6. DestroyedBlackFunds emits no Transfer. Live check: getBlackListStatus 0x59bf1abe.`

**§8.2, lines 104-109.** Replace the victim, story and sends lines with:
`"as_of": "2024-06-05T23:59:59Z",
  "victim": { "alias": "Victim A.H.", "age_band": null, "exchange_used": "Crypto.com" },
  "story": { "scam_app": "string", "platform": "text message", "first_contact": "2023-11", "summary": "string", "facts_source": "¶¶ 38-46" },
  "sends": [
    { "chain": "ethereum", "tx_hash": "0x...", "from": "0xd95...", "to": "0xcf9b...", "token": "ETH",
      "amount": "26.61", "time": "...", "validated": true, "validation_method": "resolver" }
  ],  // six sends from ¶ 69`

**§8.3.** Make these changes:
- `method`: add `"as_of_block"`, `"engine_version"`, `"max_api_calls": 400`, `"confidence_model": {...}`.
- Top level: add `"status": "done | partial | error"` and `"seeds": [{seed_id, victim_alias, tx_hash, token, amount}]`.
- `kind`: `victim | entry | intermediate | consolidation | holding | exchange_deposit | exchange_hot | service | bridge | mixer | sanctioned | unknown`.
- `label_source`: `blockscout_oli | brianleect_2023 | seed | ofac | sweep_rule | null`.
- `frozen`: `{ "status": "frozen|unfrozen|destroyed|none", "frozen_at", "freeze_tx", "destroyed_amount", "destroyed_tx" }`, evaluated at as_of.
- Nodes: add `history_complete` and `transfer_count`.
- Edges and endpoints: add `attributed_by_seed`.
- Endpoint `reason`: add `capped | high_volume | budget | time_cap | swap_unresolved | tether_destroyed`.
- `other_payers`: change to `{ "tx_hash", "entry_address", "source_exchange", "amount", "token", "time" }`, plus `"window_end"`.
- `stats`: add `fetch_errors`, `dropped: {capped, dust, zero_value, self_transfer}`, `api_calls_by_source`.

**§8.4.** Replace these signatures:
- `get_transfers(chain, address, token=None, before=None, after=None)` → `get_transfers(chain, address, token=None, as_of=None, after=None)`, returning Transfer `{chain, tx_hash, log_index, tx_index, block, time, from, to, token, contract, amount_base, decimals, kind}`. It drops zero-value and self transfers and matches on contract only.
- `get_balance(chain, address, token="USDT") -> float` → `get_balance(chain, address, token="USDT", block=None) -> int`.
- `freeze_status(chain, address)` → `freeze_status(chain, address, as_of=None)`, a local dump lookup.
- `check` evidence: the typed schema from issue 13.
- `chainabuse_reports` returns `{report_id, address, chain, category, reported_at, checked, trusted, claimed_losses}`.
- `freeze_backtest` returns `{detection_lag_median_h, p90_h, escape_share_median, n, n_skipped, population, method}`.
- Line 176: replace with `# voice: Cartesia webhook tool posts to /intake/voice/story and returns {case_code, upload_url}. No SMS.`
- Line 178: append `Stub traces carry "source": "hand_built". The scoreboard refuses them.`

**§8.5.** Replace these rows:
- `POST /intake/screenshot` → `POST /intake/{case_code}/screenshot`.
- `POST /voice/*` → `POST /intake/voice/story` (Cartesia tool) and `GET /intake/active`, both owned by CK.
- Add rows: `GET /c/{code}` (upload page), `POST /demo/reset` (Ishaan).

**§9.1.2.** Replace:
`Done = starting from DOJ A-1 (\`0xcf9…485027\`) it reaches A-7 / A-9 blind (holdout respected).`
With:
`Milestone Sat 12 PM: a USDT start at A-1 reaches A-6. Done: from A.H.'s six ETH sends it reaches A-6, A-7, A-8 and A-9 blind, A.H.'s amounts land inside the ¶ 74 bands, the conservation test passes, and two runs are byte-identical.`

**§9.1.3.** Replace with:
`classify() explains nodes after the trace, using claude-haiku-4-5, features only, cached by feature hash. Stop rules live in engine/stop_rules.py and are deterministic. scripts/eval_classifier.py prints x/30.`

**§9.1.4.** Replace with:
`write_case() uses claude-opus-5-5 at effort low, with templates and the facts dict. writer.validate runs on every generation. Offline fixture tests. Pre-generated packets for every curated case.`

**§9.2.1.** Append:
`Each teammate gets their own Etherscan key. Also get a Blockscout PRO key, an Alchemy archive URL and a Tronscan key. In the first hour, ship cache.py with record mode and record the KILL_TEST §2 addresses so Ishaan can start.`

**§9.2.2.** Replace the Blockscout URL sentence with the Etherscan v2 block-window spec from issue 4. Add txlist and txlistinternal.

**§9.2.4.** Replace with:
`freezes.py: a one-time dump of all three events into data/freezes_eth.json, with the tail refreshed. Done: A-7 frozen 20140818 and destroyed 4,340,000 at 21196374.`

**§9.2.5.** Replace `community Etherscan label datasets on GitHub` with:
`Blockscout metadata service, then brianleect with a slug allowlist (not dawsbot), then a seed file and infra_allowlist.json. OFAC is ETH plus USDT 0x entries, lowercased.`

**§9.2.8.** Replace with the payment-based entry-layer definition from issue 6.

**§9.2.9.** Replace:
`Done = \`check()\` on A-7 returns hold with evidence; on a Binance hot wallet it returns allow.`
With:
`Done: check() holds d95 (or A-1) and the gold first hop. It allows a Binance hot wallet, the Universal Router and the victim. It allows planted poison transfers. It runs as a pure lookup under 50 ms. Invalid input returns 400.`

**§9.3.1.** Replace `a Twilio trial (verify your phone) and a Cartesia key` with:
`a Cartesia key and a Cartesia number. Hunt candidates on chainabuse.com by hand, not through the API. Run the candidate filter script. Shortlist 3 by midnight.`

**§9.3.3.** Append:
`Build it from the PDF images on p.17 to 19, not the .txt. 15 entries. Then run proof/resolve_ohnd.py.`

**§9.3.4.** Replace `run the engine from the victims' first USDT addresses and compare endpoints and per-wallet totals with DOJ ¶¶ 83-85` with:
`the three-tier scoreboard from §5.1.`

**§9.3.7.** Replace with:
`**Sat morning:** Cartesia agent in the Playground with one webhook tool (about 1 hour). Then screenshot extraction plus on-chain validation. Sat 6 PM gate: a real call creates a Case visible at GET /intake/active.`

**§9.3, add item 8:**
`Sat: 30 to 60 minutes at the Coinbase booth on withdrawal screening. 2 to 3 quotes, attributed by role. Own Q&A prep.`

**§9.4.3.** Append `Polls GET /intake/active every 1 s. QR and short link. Replay intake button.`

**§9.4.8.** Append `Screen-record each feature as it lands. Truncate live addresses.`

**§10, line 240.** Replace:
`- **Should:** voice + screenshot intake, weekend scan, Tron adapter.`
With:
`- **Gates:** Sat 12 PM, if the engine does not reach A-6 and A-7, scope freezes to replay, check and packet. Sat 6 PM, if voice does not work end to end, drop Cartesia. Snapshot frozen at Sat 10 PM. Cut first: Tron, weekend scan, live call. Sun 8 AM: refresh freezes and gold-case balance.`

**§11 table.** Replace the rows with:
`Overall | Most Technically Complex Hack | Hacker's Choice | Best People-First Hack | Microsoft Built for the Real World + Microsoft Customer Impact Award | Anthropic (thoughtful use of Claude, where it could go wrong) | Cartesia (only if voice ships) | Armadin (re-check criteria Sat AM)`

**§12, add:**
`- Live addresses truncated in the video, Devpost and slides. Live data is gitignored.
- Reports alone never cause a hold. Entry addresses found through other payers are warn only and never exported.
- The packet footer is written by code: "Hound never charges or asks for keys."`

---

## 3. Decisions Ishaan must make tonight

1. **Cartesia track: commit or drop.** Committing makes voice a Must for CK on Saturday morning (about 1 hour of Playground setup plus routes). It costs about $5 on a card, and a recorded clip is the fallback. **Recommendation: commit, with the Sat 6 PM drop gate.**
2. **Merge model.** Owners self-merge their own directories, or you merge everything. You don't have admin, so you can't enforce either one. **Recommendation: self-merge, with your review only on models.py, api.py, the engine and schemas.**
3. **Scope gates.** Agree the Sat 12 PM and 6 PM gates and the cut order (Tron, weekend scan, live call, backward expansion) with the team tonight, before anyone is tired. **Recommendation: yes, as written.**
4. **Amount scoring basis.** Score on our realised swap output and show DOJ's ¶69 USD values beside it, or seed the lots at DOJ's USD values so the numbers match DOJ on purpose. **Recommendation: realised output, with the delta explained.** Seeding at DOJ's values would no longer follow the real chain amounts.
5. **Tron.** Build tron.py Saturday morning only if CK's best gold-case candidate by midnight is on Tron. Otherwise it stays last. **Recommendation: let CK's shortlist decide.**
6. **Live hold target on stage.** Use the gold case's first hop if one exists by 10 AM. Otherwise use the d95 replay hold as a counterfactual. **Recommendation: depends on the gold case; script both versions.**
7. **Is the replay start "blind" enough?** A-1 was found by walking back from the frozen wallets. Either disclose it and start from the resolved d95 sends, or stretch to resolve d95 forward. **Recommendation: disclose, start from the six d95 sends, and have the scripted answer ready.**
---

# Part 2: completeness critic (N1 to N13)

I found 13 new items. I checked them against the brief, the complaint, `hound/examples/ohnd_transfers.json` (414 real transfers) and the Etherscan docs. None of them repeats a synthesis issue. I made no Blockscout calls.

## CRITICAL

**N1. Setting `as_of = 2024-06-05` cuts the replay off before A.H.'s money reaches A-8, and probably A-9. That makes "Done" impossible.**
- **Evidence:** the fixture shows A-6 → A-8 sends continuing after Jun 5:
  - Jun 8: 190,000
  - Jun 15: 220,000
  - Jun 19: 260,000
  - Jun 24: 260,000
- **Why it matters:**
  - A.H.'s lots arrive at A-6 on May 21-30 (¶71) and leave by FIFO, so part of ¶74's A-8 11,954 can leave after Jun 5.
  - None of A-6's sends to A-9 after May 15 appear in the fixture, so A-9's 43,071 may also arrive after Jun 5.
  - Synthesis issue 1's "Done" (reach A-8 and A-9) and the amount bands both depend on this.
- **Fix:**
  - Split `as_of` into two values:
    - `data_cutoff_block = 20170085`, one block before the last freeze (A-8, block 20170086).
    - `freeze_visibility = hidden`: the engine treats every freeze as unknown, and the UI reveals them only after the run.
  - Keep Jun 5 only as the story date for the hold counterfactual.
  - Test: from the six d95 sends, all three of A-7, A-8 and A-9 get more than 0 attributed.
- **Owner:** Ishaan (engine), CK (scoreboard).
- **Brief:** §5.1 (the added `as_of` line), §8.2, synthesis issue 3.

**N2. Address-poisoning lookalikes match DOJ's truncated `prefix…suffix` strings.**
- **Evidence:** the fixture has 13 zero-value transfers to lookalikes, for example:
  - `0x58e7c560…b2d0dcb`, `0x58e1a9cc…2d0dcb` and `0x58e37f9f…12d0dcb` all match A-6's "58e…b2d0dcb".
  - `0xdf63d4d3…0ed53f` and `0xdf6ad68e…0ed53f` match A-5's "df6…f0ed53f".
  - `0x7835bc7b…1fda1a06` matches A-2's "783…2da1a06".
- **What breaks:**
  - The issue 15 resolver will hit ">1 match" and fail.
  - The holdout grep regex fires on poison addresses in the fixtures.
  - The scoreboard can credit "reached A-6" for a poison address.
  - The brief's "A-6 confirmed by suffix" claim also rests only on the suffix.
- **Fix:**
  - The resolver drops zero-value and non-canonical-contract rows before matching, and requires amount and date to match.
  - The scoreboard matches on full resolved addresses from `resolved.json` only, never on a regex.
  - The holdout test uses the full addresses, plus prefix/suffix only for the entries that are still unresolved.
  - Add a fixture test: the poison lookalikes are never trace nodes.
- **Owner:** CK (resolver, scoreboard, test), Jinka (filter).
- **Brief:** §5.1 line 47, synthesis issues 14 and 15.

**N3. Etherscan `tokentx` has no `logIndex`, but synthesis issues 4, 7 and 11 depend on it.**
- **Evidence:** the docs at docs.etherscan.io/api-reference/endpoint/tokentx list 22 fields, including `transactionIndex` but not `logIndex`.
- **What breaks:**
  - Dedupe on `(hash, logIndex)` across block-window pages can't run.
  - The FIFO sort key `(block, tx_index, log_index)` is undefined.
  - Two identical transfers inside one tx collapse into one, or overlapping pages double-count.
  - The fixture's `log_index` came from Blockscout, which Etherscan doesn't match.
- **Fix:**
  - Primary: fetch USDT `Transfer` logs with Etherscan v2 `module=logs&action=getLogs`, filtering on topic0 = Transfer `0xddf252ad…` and `topic1`/`topic2` = the padded address (both indexed). These logs include `logIndex` and `transactionIndex`. Use `tokentx` only as a cross-check.
  - Fallback: dedupe as a multiset on `(hash, from, to, value)` with an occurrence counter.
- **Owner:** Jinka.
- **Brief:** §8.4, §9.2.2, synthesis issue 4.

## HIGH

**N4. The 25 s trace deadline and the 400-call budget contradict each other, and the Next proxy will cut long requests.**
- **Evidence:** at 2.5 calls/s, 400 calls take 160 s, so a live trace always ends `partial`. Next.js rewrites to an external host proxy with a default timeout of about 30 s (`experimental.proxyTimeout`; I have not run this to confirm).
- **Fix:**
  - `POST /cases/{id}/trace` returns `{trace_id, status:"running"}` straight away and runs the trace as a FastAPI background task.
  - `GET /traces/{id}` returns the trace so far plus `audit_log`, and the UI polls it every 1 s. This also drives the "hops unfold" animation.
  - The deadline becomes 120 s for live runs. Readonly replays finish in under 2 s.
- **Owner:** Ishaan (route), Aaryan (polling).
- **Brief:** §8.5, §9.4.2, synthesis issue 7.

**N5. Readonly demo mode breaks Hyphenate's "judges may try their own scenario". Hyphenate is the $8K track.**
- **Problem:** in readonly mode, any judge-supplied address raises `CacheMiss`.
- **Fix:**
  - Add `HOUND_CACHE_MODE=prefer_cache`: cache hits are served, and misses go live with `max_api_calls=60` and a 60 s deadline, returning a partial trace with honest endpoints.
  - The demo uses `prefer_cache`; tests stay `readonly`.
  - Add a "try your own" box that takes a tx hash and builds the Case from the tx receipt.
  - The demo laptop needs one teammate's Etherscan key for this.
- **Owner:** Jinka (cache mode), Ishaan (route).
- **Brief:** §6, §11 Hyphenate row, synthesis issues 10 and 19.

**N6. The swap join assumes USDT comes back to the same address. Aggregators often route the output elsewhere, and WETH paths break the join.**
- **Problem:** aggregator calls (1inch, 0x, Universal Router) can set `recipient` to a different address, for example A-2 directly. A wrap followed by a swap spans two transactions. Gas, and dust left at the router, break the conservation test.
- **Fix:**
  - For each ETH-out from a swap address, fetch `eth_getTransactionReceipt` (archive RPC) and read every USDT `Transfer` log in that tx. The output edge goes to whichever non-infrastructure `to` receives the USDT.
  - WETH: treat a WETH `Deposit` by the same address within 50 blocks as a lot carry-over.
  - Convert lots proportionally with integer floor and give the remainder to the largest lot, so conservation holds to the micro-unit.
  - If there is no match, emit `swap_unresolved` as in the synthesis.
- **Owner:** Ishaan, with Jinka for the receipt call.
- **Brief:** §4.3, synthesis issues 1 and 11.

**N7. Asking a 60+ victim for a block-explorer screenshot is an accessibility barrier.**
- **Problem:** Cartesia judges weight accessibility at 25%. A victim using the Crypto.com app has withdrawal history, not an explorer page.
- **Fix:**
  - Accept the exchange's withdrawal-detail screenshot. Claude extracts the partial hash or address, the amount and the time.
  - Code then resolves the send the same way the d95 resolver does: Etherscan `tokentx`/`txlist` on that exchange's seed hot wallets, inside a narrow block window (time ±2 h converted to blocks). Match amount ±0.5% and the prefix/suffix.
  - The upload page uses a single large button, 18px+ text, ARIA labels, and a "type it instead" text field.
- **Owner:** CK (resolver), Jinka (hot-wallet seeds), Aaryan (page).
- **Brief:** §4.1, §9.3.8, synthesis issue 5.

**N8. A quick-tunnel URL changes on every restart, and the Cartesia tool URL lives in CK's account.**
- **Problem:**
  - `cloudflared tunnel --url` gives a random `*.trycloudflare.com` URL. A laptop sleep or a switch to the phone hotspot means a new URL, so the webhook goes stale and the QR code dies.
  - There is no "short link" either.
- **Fix:**
  - Use a named Cloudflare tunnel on a domain the team already has on Cloudflare, or an ngrok free static domain for the webhook only (ngrok's interstitial page affects browsers, not API calls).
  - Serve `/c/{code}` from the same stable host.
  - Run `caffeinate -dims` on the demo laptop.
  - Write a checklist line: "Cartesia tool URL = PUBLIC_BASE_URL, verified Sun 8 AM".
- **Owner:** Ishaan (tunnel), CK (agent config).
- **Brief:** §7 env, §10 Sun 8 AM.

## MEDIUM

**N9. The committed cache snapshot would publish Chainabuse and LLM data, plus caller phone numbers.**
- **Problem:**
  - Synthesis issue 10 commits `make warm` output that includes "the scan" (Chainabuse responses, proprietary per issue 17).
  - The LLM cache holds story text.
  - Recorded Cartesia tool payloads may carry the caller ID.
- **Fix:**
  - Namespace the cache by source (`etherscan/`, `rpc/`, `blockscout/`, `chainabuse/`, `llm/`). Commit only the chain namespaces.
  - Scrub `caller`/`from_number` from the replay-intake fixtures.
  - `test_public_data.py` asserts that no committed file contains a phone-number regex match, a Chainabuse namespace, or an `.env` value.
  - Add a `gitleaks` pre-commit hook.
- **Owner:** Jinka (namespaces), CK (scrub, test).
- **Brief:** §7, §12.

**N10. There is no historical ETH/USD price source.**
- **Problem:** native-ETH `other_payers` needs a "≥100 USDT-equivalent" test, and the scoreboard shows DOJ's USD values next to ours. Neither has a defined price. Etherscan's `ethdailyprice` is a PRO endpoint.
- **Fix:**
  - Commit `data/prices/eth_usd_daily.csv` covering 2024-03..06 and 2026-09..10, pulled once from the CoinGecko demo API.
  - Use the realised swap rate wherever a swap exists.
  - Label the price source in the packet.
- **Owner:** Jinka.
- **Brief:** §8.3, synthesis issue 6.

**N11. There is no plan for Claude being down or failing at intake time. Only the writer has a fallback.**
- **Problem:** screenshot vision and the Cartesia agent (which runs an Anthropic model) both fail when Claude fails.
- **Fix:**
  - The vision call gets a 15 s timeout, then falls back to the manual hash/address entry field from N7.
  - The Cartesia agent has a non-Anthropic fallback model set in the Playground, if the catalog offers one. Otherwise use the recorded clip.
  - `classify` failures show "explainer unavailable". They never block the trace.
- **Owner:** CK (intake), Ishaan (classify).
- **Brief:** §4.4, §9.3.7.

**N12. A graph of mixed Ethereum and Tron nodes needs one per-chain key and per-chain normalisation.**
- **Problem:** a global `lower()`, which the 0x rules invite, corrupts case-sensitive Tron base58. Mixing 41-hex and base58 forms creates duplicate nodes. Bare `address` keys in `nodes`, `edges` and the watchlist can collide across chains.
- **Fix:**
  - Node id = `f"{chain}:{normalize(chain, addr)}"`, with Tron kept as base58 everywhere.
  - `check` infers the chain from the format and returns 400 if it disagrees with `chain=`.
  - Test: the same 20 bytes on both chains produce 2 distinct nodes.
- **Owner:** Jinka (normalise), Ishaan (engine keys).
- **Brief:** §8.1, §8.3.

**N13. The environment drifts between machines.**
- **Problem:**
  - `hound/backend/.venv` is Python 3.14, but the brief says 3.12. There is a `requirements.txt` and no uv lock.
  - `next build` bakes the rewrite destinations in at build time, so changing `HOUND_API_URL` at `next start` won't apply.
- **Fix:**
  - Use `uv python pin 3.12` and `uv lock`.
  - Commit `.nvmrc`.
  - `make demo` rebuilds the web app with the demo env.
  - Before the pitch: turn on a Focus/Do Not Disturb mode, set browser zoom to 125%, and close Claude Code (so it doesn't hold the key).
- **Owner:** Ishaan.
- **Brief:** §7, synthesis issues 18 and 19.

The two items to settle tonight are N1 and N3. N1 means changing the replay's `as_of` design before Ishaan writes the engine against it. N3 means switching the primary fetch to `getLogs` before Jinka builds pagination on `tokentx`.