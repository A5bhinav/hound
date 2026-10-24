# Cartesia voice intake (CK) — agent config, Sat morning

Gate: Sat 6 PM. Recorded clip is the default on stage; live call for Cartesia judges.

## What the agent does (BRIEF §0 voice decision, AUDIT N7/N8/N11)
1. Opens: "This is Hound, a free service that helps scam victims. I never ask for money, passwords, seed phrases or keys."
2. Collects the story in plain questions, one at a time: what app or website, how they were contacted (platform), roughly when it started, which exchange they used, the total they sent. Age band only if offered.
3. Calls the tool `open_case` once the story is clear. Reads back the case code letter by letter and the link, then tells them to send a picture of the payment screen (exchange withdrawal detail is fine) or type the details on that page.
4. Never promises recovery. Says "reported, not proven" language only. Ends with "Keep this case code."

## Tool: `open_case`
- Method POST, URL `https://<backend ngrok domain>/intake/voice/story` (stable reserved domain; Ishaan owns the tunnel; verify Sun 8 AM). The web host's proxy also forwards `https://<web host>/api/intake/voice/story`. Register with `python scripts/cartesia_agent.py --tool-url <url>`.
- Header `X-Hound-Intake-Token: {HOUND_INTAKE_TOKEN}` (set the same value in backend .env).
- Body: `{"story": {"scam_app": str, "platform": str, "first_contact": "YYYY-MM", "summary": str}, "victim": {"alias": "Caller", "age_band": "60+|unknown", "exchange_used": str}}`
- Response: `{"case_code": "K7M2PQ", "upload_url": ".../c/K7M2PQ", "say": "..."}` — the agent speaks `say`.
- Never send the caller's number in the body; the backend scrubs phone numbers anyway (N9).

## Cartesia Playground steps
1. Agents → New agent. Model: Claude (fallback: any non-Anthropic model offered, N11). Voice: calm, slow; use Sonic.
2. Paste the system prompt from §"What the agent does". Add tool `open_case` with the schema above.
3. Phone Numbers → provision a number → attach the agent.
4. Test call from a teammate's phone; confirm `GET /intake/active` shows the session on the Intake page and the QR/link works on a phone.
5. Record the clip for the pitch video (consented teammate as the caller, no real victim data).

## Env
`CARTESIA_API_KEY` (set), `CARTESIA_AGENT_ID` (after step 1), `HOUND_INTAKE_TOKEN` (random, shared with the tool header), `PUBLIC_BASE_URL` (tunnel).
