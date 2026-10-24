# Code review findings for teammates (Fri Oct 23, ~11 PM)

From the 6-dimension adversarial code review of main (every finding reproduced or verified by a second agent). Ishaan's areas (engine, API, writer) are being fixed separately. These are yours: tell your agent to read this file, check each finding still applies on current main, fix it with a test, and open a PR.

## Aaryan (web/)

### [high] contracts-3 (web/src/components/CaseCard.tsx:15)
- Problem: The case card and home page sum send amounts and print the total as USDT. The OHND replay sends are ETH, so the headline number is wrong.
- Evidence: examples/ohnd_replay.case.json has 6 sends with token 'ETH' totalling 114.506 ETH. CaseCard.tsx:15 and :22 render '114.51 USDT sent', page.tsx:41 shows the same on the home card, and CaseCard.tsx:43 lists each send as '8.4 USDT'. This is the first number judges see. BRIEF 8.1 says amounts are 'whole token units', so the token must travel with the number.
- Fix: Format by s.token: show `${amount} ${token}` per send, and sum per token. For a USDT-equivalent headline, use trace.swaps.per_seed[*].usdt_out (377,184.7 USDT) with a 'swapped to' note.

### [high] contracts-5 (web/src/lib/api.ts:53)
- Problem: The web reads the POST /cases/{id}/trace response as the full Trace. The agreed async route (AUDIT N4) returns {trace_id, status:'running'} and serves partial traces from GET /traces/{id}. The schema's status enum (done|partial|error) has no running state, so a rewrite that follows N4 either crashes the UI or fails validate_trace.
- Evidence: TraceGraph.tsx useMemo runs `trace.edges.map` and CaseCard runs `trace.endpoints.map`. Both throw on {trace_id, status:'running'}. The schema status enum is ['done','partial','error'], and trace.py:237 validates only at the end, so a 'trace so far' snapshot has no valid shape. types.ts Trace also has no status, seeds, swaps, replay or audit_log.
- Fix: Agree on one shape before the rewrite merges. Add 'running' to the trace.schema status enum, and make GET /traces/{id} return a schema-valid partial Trace (empty arrays are fine). In web, POST, then poll GET /traces/{trace_id} until status != 'running'. Add status, replay, seeds, swaps and victim_remaining to types.ts.

### [medium] contracts-7 (web/src/components/TraceGraph.tsx:32)
- Problem: In replay mode (method.freeze_visibility='hidden'), the UI shows freezes as if they were the engine's stop. Nothing in the UI is keyed on freeze_visibility, replay, or frozen_at being after as_of. The CaseCard labels the frozen final 'Still sitting here'.
- Evidence: Example: 0xa1770e and 0xafd770 show 'TETHER FROZE THIS' with the frozen tone the moment hop 5 animates in, and the frozen legend is visible throughout. The endpoint reason is 'holding', so CaseCard.tsx:63 prints 'Still sitting here: 365,106 USDT' for a 2024 replay. The schema `replay` field is documented as 'UI must say replay, never sitting there right now', but types.ts has no replay field. BRIEF §0 says freezes are revealed after the run ('Tether froze these 16 to 20 days later').
- Fix: In tone() and nodeText(), suppress frozen styling while trace.method.freeze_visibility==='hidden' && shownHop < maxHop, then reveal with '+N days after cutoff' (frozen_at minus case.as_of). When trace.replay is true, CaseCard should say 'Was sitting here at cutoff', and endpoints whose node is frozen should get the frozen copy.

### [medium] contracts-9 (web/src/components/CaseCard.tsx:67)
- Problem: The UI shows endpoint victim_inflow as the amount 'of the victim's money' at that stop. For an explored holding or frozen node that passed some money on, inflow exceeds what is left, so downstream endpoints count the same money twice. The engine already emits victim_remaining, but types.ts and the UI ignore it.
- Evidence: trace.py:321-322 emits both victim_inflow (total tainted in) and victim_remaining (still there). Holding endpoints are explored nodes, so any onward hop puts inflow above remaining. types.ts Endpoint has no victim_remaining, and NodeDetail 'Victim money in' plus the CaseCard list both use inflow. Summing the CaseCard list overstates the recoverable total.
- Fix: Add victim_remaining to types.ts Endpoint. Show victim_remaining for holding/frozen/capped/dust reasons and victim_inflow for exchange. Have the writer follow the same rule.

### [low] contracts-11 (web/src/components/NodeDetail.tsx:32)
- Problem: The node panel prints the full address and an explorer link for every node, including the victim's own wallet (depth 0). BRIEF §0 requires live addresses to be truncated everywhere public. For a live phone or Chainabuse case this exposes the victim's address on the projected screen and in the shared link.
- Evidence: NodeDetail.tsx:32 renders `{node.address}` in full for kind 'victim'. GET /traces/{id} serves the same data with CORS '*' (api.py:24).
- Fix: When !trace.replay, render shortAddr(node.address) and drop the explorer link for kind==='victim', at minimum. Full addresses stay in the detective packet only.

### [low] contracts-12 (web/src/lib/types.ts:72)
- Problem: The web types fall behind the schema. Endpoint.reason lacks the 6 new reasons, Endpoint.balance_usdt is typed as number though the schema allows null, and Case victim/story are typed as required though the schema makes them optional. An intake case without victim/story crashes the UI.
- Evidence: schemas/case.schema.json requires only case_id, created_at, source, sends and status. CaseCard.tsx:19/28 read `c.victim.alias` and `c.story.scam_app` and page.tsx:40/43 do the same, so a screenshot or voice case created through POST /cases without story throws TypeError. CaseCard's REASON map shows raw 'high_volume' / 'swap_unresolved'.
- Fix: Regenerate types.ts from schemas/ (or hand-sync it): make victim/story optional and use `c.victim?.alias ?? 'Unnamed victim'`; add the reason values and REASON copy; allow balance_usdt: number | null.

### [medium] api-integration-10 (web/src/app/cases/[id]/page.tsx:12 + web/src/lib/api.ts traceCase)
- Problem: The case page calls POST /cases/{id}/trace on every render, so each page view, refresh or prefetch reruns the whole trace. Live, that is up to 400 calls, a 120s deadline and other_payers retries, and the server-side fetch has no timeout or abort. It also expects a full Trace from the POST. The agreed async rewrite (N4: POST returns {trace_id, status:'running'}, then poll GET /traces/{id}) will break this client as written: trace.endpoints is undefined and CaseCard crashes. The web Trace type also has no `status`, so a 'partial' trace (budget/time_cap) is shown to judges as complete.
- Evidence: page.tsx: `[c, trace] = await Promise.all([getCase(id), traceCase(id)])`. api.ts call() uses fetch with no signal or timeout. The types.ts Trace interface has no status, seeds or swaps, and the Endpoint reason union lacks capped/budget/time_cap/high_volume/swap_unresolved.
- Fix: Agree the contract now. POST /cases/{id}/trace returns {trace_id, status}; GET /traces/{id} returns the trace with top-level status running|done|partial|error. The web posts once (client action or button), polls GET /traces/{id}, and renders a 'partial' badge. In the backend, return the cached trace for an already-traced case unless ?force=1. Add an AbortSignal.timeout to fetch.

### [medium] security-public-8 (web/src/app/page.tsx:41)
- Problem: The web home page crashes against the real backend: GET /cases (api.py:50) does not return sends, but page.tsx calls c.sends.reduce(...) and c.sends[0]. The case page (cases/[id]/page.tsx:12) also fires POST /cases/{id}/trace on every render, so each public view or refresh of a QR/short link re-runs a full chain trace on the team's API keys.
- Evidence: The list_cases keys are exactly ['case_id','source','status','victim','story'], confirmed via TestClient, so c.sends is undefined → TypeError: Cannot read properties of undefined (reading 'reduce'). It only works with HOUND_DATA=fixture. traceCase() is a POST inside a server component and runs per request with cache: 'no-store'.
- Fix: Include sends in GET /cases, or add GET /cases/{id} returning the full case, since getCase depends on it. Do not just guard with ?. in the UI. Make the trace page read a cached trace (return the existing TRACES entry for the case if there is one) and run a new trace only from an explicit button.

## Jinka (hound/chain, hound/watch)

### [medium] security-public-4 (backend/hound/watch/check.py:53)
- Problem: The check fails open on freeze errors. When the on-chain isBlackListed RPC fails, fz is set to None, which throws away the local event-history status that already says 'frozen'. A Tether-frozen address that is not on the watchlist then gets 'allow'. Separately, api.py's own /check route (api.py:103) does not include watch.routes.router and does not map ValueError, so invalid input returns 500 where the brief says 400.
- Evidence: With freezes.is_blacklisted_onchain monkeypatched to raise ChainAPIError, check('ethereum', A-7) printed 'freeze_status failed…' and fz stayed None. The address was held only because it is on the watchlist; without a watchlist entry, the code path ends at _result('allow', ['no Hound data…', 'freeze status could not be checked']). TestClient GET /check?address=not-an-address returned 500 Internal Server Error. CacheMiss (offline mode) is not a ChainAPIError, so it also returns 500.
- Fix: In check.py, catch (ChainAPIError, CacheMiss) and retry with chain.freeze_status(chain_name, addr, as_of=<now ISO>), which reads the history only. If freeze state is still unknown, return 'warn', not 'allow'. In api.py, delete the duplicate /check route and call app.include_router(watch.routes.router).

### [medium] security-public-5 (backend/hound/watch/check.py:54)
- Problem: Raw adapter exception text is returned in the public /check response, and watch/routes.py does the same in its 502 detail. ChainAPIError messages from eth.rpc embed the full RPC URL. Alchemy and Infura put the API key in the URL path (AUDIT recommends an Alchemy archive key in ETH_RPC_URLS), and net._redact only masks query params whose name contains 'key'.
- Evidence: Reproduced: a ChainAPIError('https://eth-mainnet.g.alchemy.com/v2/SECRETKEY123 eth_call: timeout') from freeze RPC produced response evidence.freeze_check_error = 'https://eth-mainnet.g.alchemy.com/v2/SECRETKEY123 eth_call: timeout'. The same text goes to log.warning in eth.rpc (line ~212) and net.request_json errors. The trace engine's _redact regex only catches key=value, not path keys.
- Fix: Set evidence['freeze_check_error'] = 'freeze RPC unavailable' and routes.py detail='chain data unavailable'. In _rpc_once, strip the URL to scheme+host before putting it in exception text.
