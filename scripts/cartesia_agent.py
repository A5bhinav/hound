"""Create (or update) the Hound voice-intake agent on Cartesia Managed Agents.

    CARTESIA_API_KEY=sk_car_... python scripts/cartesia_agent.py [--number] [--tool-url URL]

Reads CARTESIA_API_KEY, HOUND_INTAKE_TOKEN and HOUND_PUBLIC_TOOL_URL from the env or repo-root
.env. Creates the `open_case` webhook tool (token sent as a Cartesia secret header), the agent
(AUDIT issue 5: immediate tool execution, welcome < 8 words with the disclosure line, noise
suppression max, an Anthropic model from the managed catalog), and with --number provisions a
Cartesia US number and attaches it. Re-running updates the same tool/agent (ids kept in .env).
Writes CARTESIA_AGENT_ID / CARTESIA_TOOL_ID / CARTESIA_PHONE_NUMBER back to .env. No secrets
are printed.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
API = "https://api.cartesia.ai"
VERSION = "2026-08-14"

INSTRUCTIONS = """You are Hound, a free phone service that helps people who were scammed out of cryptocurrency.
You never ask for money, passwords, seed phrases, recovery phrases or private keys. If the caller offers one, stop them.
The current local time is {{system__time}}. Use it to turn "five months ago" or "last spring" into a month and year yourself.

How to talk:
- Speak slowly and kindly. Many callers are older and upset. Keep each turn to one or two short sentences.
- When the caller pauses, say nothing and wait. Never fill silence with "mm-hm", "take your time" or half words.
- Ask one question at a time, and only for what you still need.
- Listen to everything they say and keep it. If an answer already covers a later question, or you can infer it with
  confidence from what they said, do not ask it. Example: if they bought and sent the crypto inside the scam app itself,
  that app is also where they sent from, so don't ask for an exchange.
- If you clearly understood an answer, accept it and move on. Do not ask them to confirm it. Ask again only when you are
  genuinely unsure about something important (the platform, roughly when, roughly how much). Never guess about the
  person (their age, their name, how much they lost) when they haven't said it.
- Never say "anything else?" or ask them to repeat what they already told you.

What you need for the case (in any order, as the conversation goes):
1. their first name (if they would rather not say, call them "friend"),
2. the app or website they invested through (scam_app; a description like "a blue app with a face logo" is fine),
3. how the scammer first contacted them, e.g. a text, WhatsApp, a dating app (platform),
4. roughly when it started, as a month and year (first_contact, YYYY-MM; work it out from the current time),
5. which exchange they sent the money from, if it was not the scam app itself (exchange_used; for Crypto.com say
   "Crypto dot com" out loud and write Crypto.com in the tool),
6. what happened and roughly how much they sent, in one question (summary, one or two sentences).
Ask their age band only if they bring it up (60+ or unknown). Never ask for a last name, address or phone number.
Use their first name now and then, not in every sentence.

As soon as you have these, call the open_case tool once. Then say their first name, that their case is open, and the
case code from the tool result, letter by letter, slowly, twice. Then read the tool result's "say" line.
Hound does not send text messages: never mention texting.

Then stay on the line and walk them through the web page, one step at a time, waiting for each step to be done:
1. Open the web browser on your phone or computer and go to the website from the "say" line. Say it as words, for
   example "hound help, dot vercel, dot app". Spell it letter by letter only if they ask.
2. At the top of the page, press "Check my case", and type the case code.
3. Press "Send a picture of your payment". Open the app you used to send the money, find that payment, and take a
   screenshot. Back on the Hound page, press "Choose the picture of my payment" and pick that screenshot.
4. If they can't take a screenshot, press "I can't take a picture. Let me type it instead" and type the details.
After they say they sent it, call check_upload with the case code and read its "say" line. If it hasn't arrived or is
still being checked, wait about ten seconds and call it again, up to four times. If another picture is needed, read the
reason and help them try again. If they get stuck, ask what they see on the screen and guide them from that.

The only web address you may give the caller to visit is the one in the "say" line; never make up another. That rule is
only about where you send them: you may say the name of any exchange, app or website they mention.

Never promise the money will come back. Say the case is reported, not proven, and that Hound sends the evidence to the
exchange and to the FBI's IC3. End with their first name and: "Keep this case code." Then end the call."""

INITIAL = "Hi, this is Hound, here to help. We never ask for money. What happened?"  # warm, short, with the disclosure line


def load_env() -> dict[str, str]:
    env = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    env.update({k: v for k, v in os.environ.items() if k.startswith(("CARTESIA_", "HOUND_"))})
    return env


def save_env(**kv: str) -> None:
    lines = [l for l in ENV.read_text().splitlines() if l.split("=", 1)[0] not in kv] if ENV.exists() else []
    lines += [f"{k}={v}" for k, v in kv.items()]
    ENV.write_text("\n".join(lines) + "\n")
    ENV.chmod(0o600)


def call(key: str, method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {key}", "Cartesia-Version": VERSION,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:600]}")


def pick_model(key: str) -> str:
    models = call(key, "GET", "/v1/agents/models")
    rows = models.get("data", models) if isinstance(models, dict) else models
    claude = [m for m in rows if "anthropic" in json.dumps(m).lower() or "claude" in str(m.get("id", "")).lower()]
    if not claude:
        print("no Anthropic model in the catalog; using the first available (AUDIT N11 fallback)")
        return rows[0]["id"]
    for pref in ("haiku", "sonnet"):  # fast first: voice latency matters more than depth here
        for m in claude:
            if pref in m["id"].lower():
                return m["id"]
    return claude[0]["id"]


def pick_voice(key: str, env: dict) -> str:
    if env.get("CARTESIA_VOICE_ID"):
        return env["CARTESIA_VOICE_ID"]
    req = urllib.request.Request(API + "/voices?limit=100", headers={
        "Authorization": f"Bearer {key}", "Cartesia-Version": VERSION})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    voices = data.get("data", data) if isinstance(data, dict) else data
    en = [v for v in voices if v.get("language") in ("en", None)]
    for word in ("calm", "gentle", "warm", "soothing", "friendly"):
        for v in en:
            if word in (v.get("description", "") + " " + v.get("name", "")).lower():
                return v["id"]
    return en[0]["id"]


def tool_body(url: str, token: str) -> dict:
    s = lambda d: {"type": "string", "description": d}
    return {
        "type": "webhook", "name": "open_case",
        "description": "Open a Hound case once you know the scam app, how they were contacted, when it started, "
                       "the exchange used and a short summary. Returns case_code, upload_url and a 'say' line "
                       "to read to the caller exactly.",
        "pre_tool_speech": "auto", "execution_mode": "immediate", "response_timeout_secs": 20,
        "api_schema": {
            "url": url, "method": "POST",
            "request_headers": {"X-Hound-Intake-Token": {
                "type": "secret", "secret_value": token,
                "secret_description": "Hound intake token (shared with the backend HOUND_INTAKE_TOKEN)"}},
            "request_body_schema": {"type": "object", "required": ["story", "victim"], "properties": {
                # Filled by Cartesia from the call itself, so the link can be texted; the agent never asks for it.
                "caller_number": {"type": "string", "dynamic_variable": "system__caller_id"},
                "story": {"type": "object", "description": "What happened", "required": ["summary"], "properties": {
                    "scam_app": s("App or website they invested through"),
                    "platform": s("How the scammer first contacted them, e.g. text message, WhatsApp, dating app"),
                    "first_contact": s("When it started, YYYY-MM"),
                    "summary": s("One or two sentences: what happened and roughly how much they sent")}},
                "victim": {"type": "object", "description": "About the caller: first name only, no last names or phone numbers",
                           "properties": {
                               "alias": s("The caller's first name only, or Caller if they did not give one"),
                               "age_band": {"type": "string", "enum": ["60+", "unknown"],
                                            "description": "Only if the caller mentioned it, else unknown"},
                               "exchange_used": s("Exchange they sent from, e.g. Coinbase")}}}},
        },
    }


def status_tool_body(url: str, token: str) -> dict:
    return {
        "type": "webhook", "name": "check_upload",
        "description": "While walking the caller through the upload page: check whether their payment picture or "
                       "typed details arrived and were confirmed. Returns status and a 'say' line to read to the caller.",
        "pre_tool_speech": "auto", "execution_mode": "immediate", "response_timeout_secs": 10,
        "api_schema": {
            "url": url, "method": "POST",
            "request_headers": {"X-Hound-Intake-Token": {
                "type": "secret", "secret_value": token,
                "secret_description": "Hound intake token (shared with the backend HOUND_INTAKE_TOKEN)"}},
            "request_body_schema": {"type": "object", "required": ["case_code"], "properties": {
                "case_code": {"type": "string", "description": "The 6-character case code from open_case, no spaces"}}},
        },
    }


def agent_body(model: str, voice: str, tool_ids: list[str]) -> dict:
    return {"name": "Hound intake", "description": "Free scam-victim intake line (Cal Hacks 13.0)", "config": {
        "instructions": INSTRUCTIONS, "initial_message": INITIAL,
        "language": {"primary": "en"},
        "model": {"id": model, "fallback_strategy": {"type": "auto"}},  # some models fix temperature
        "audio": {"input": {"noise_suppression": "max", "keyterms": ["Hound", "Coinbase", "Crypto.com", "Binance",
                                                                     "Kraken", "USDT", "Tether", "WhatsApp"]},
                  "output": {"voice_id": voice, "speed": 0.9, "emotion": "calm"}},
        "turn": {"inactivity_end_call_secs": 120, "inactivity_check_in_secs": 12},
        "tools": [{"id": t} for t in tool_ids],
        # skip_turn: when the caller asks for a moment, stay quiet instead of talking over them.
        "system_tools": {"end_call": {"description": None, "pre_tool_speech": "auto"},
                         "skip_turn": {"wait_timeout_secs": 30}},
        "timezone": "America/Los_Angeles",
    }}


def main(argv: list[str]) -> int:
    env = load_env()
    key, token = env.get("CARTESIA_API_KEY"), env.get("HOUND_INTAKE_TOKEN")
    url = argv[argv.index("--tool-url") + 1] if "--tool-url" in argv else env.get("HOUND_PUBLIC_TOOL_URL")
    if not (key and token and url):
        sys.exit("need CARTESIA_API_KEY, HOUND_INTAKE_TOKEN and HOUND_PUBLIC_TOOL_URL (env or .env)")
    model, voice = pick_model(key), pick_voice(key, env)
    print(f"model {model}, voice {voice}")

    if env.get("CARTESIA_TOOL_ID"):
        patch = {k: v for k, v in tool_body(url, token).items() if k != "type"}  # type is fixed at create
        call(key, "PATCH", f"/v1/agents/tools/{env['CARTESIA_TOOL_ID']}", patch)
        tool_id = env["CARTESIA_TOOL_ID"]
    else:
        tool_id = call(key, "POST", "/v1/agents/tools", tool_body(url, token))["id"]
        save_env(CARTESIA_TOOL_ID=tool_id)
    print(f"tool open_case -> {url} ({tool_id})")

    status_url = url.rsplit("/", 1)[0] + "/status"  # .../intake/voice/story -> .../intake/voice/status
    if env.get("CARTESIA_STATUS_TOOL_ID"):
        patch = {k: v for k, v in status_tool_body(status_url, token).items() if k != "type"}
        call(key, "PATCH", f"/v1/agents/tools/{env['CARTESIA_STATUS_TOOL_ID']}", patch)
        status_id = env["CARTESIA_STATUS_TOOL_ID"]
    else:
        status_id = call(key, "POST", "/v1/agents/tools", status_tool_body(status_url, token))["id"]
        save_env(CARTESIA_STATUS_TOOL_ID=status_id)
    print(f"tool check_upload -> {status_url} ({status_id})")

    if env.get("CARTESIA_AGENT_ID"):
        call(key, "PATCH", f"/v1/agents/{env['CARTESIA_AGENT_ID']}", agent_body(model, voice, [tool_id, status_id]))
        agent_id = env["CARTESIA_AGENT_ID"]
    else:
        agent_id = call(key, "POST", "/v1/agents", agent_body(model, voice, [tool_id, status_id]))["id"]
    save_env(CARTESIA_TOOL_ID=tool_id, CARTESIA_AGENT_ID=agent_id)
    print(f"agent {agent_id}")

    if "--number" in argv:
        number = env.get("CARTESIA_PHONE_NUMBER_ID")
        if not number:
            row = call(key, "POST", "/agents/phone-numbers/provision", {"label": "Hound intake"})
            number = row["id"]
            save_env(CARTESIA_PHONE_NUMBER_ID=number, CARTESIA_PHONE_NUMBER=row.get("number") or row.get("phone_number", ""))
        row = call(key, "PATCH", f"/agents/phone-numbers/{number}", {"agent_id": agent_id})
        print(f"number {row.get("number") or row.get("phone_number") or load_env().get('CARTESIA_PHONE_NUMBER')} -> agent {agent_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
