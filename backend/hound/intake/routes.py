"""Victim intake (CK, BRIEF §4.1 / §9.3, AUDIT N7, N9, N11, security fix 11:42 PM).

Flow: the Cartesia phone agent collects the story and calls POST /intake/voice/story (a tool
webhook). We open a session with a short case code and read back the upload link. The victim
opens /c/{code} on their phone and uploads a screenshot of the send (exchange withdrawal detail
accepted) or types the hash/address instead. We extract {tx_hash | to address, amount, time},
validate the send ON CHAIN (receipt, amount, prefix/suffix), build a Case, and only then call
hound.api.mark_verified(case_id) so the case can feed the watchlist.

Nothing here trusts the client: a typed hash is only accepted once the chain confirms a send from
the victim; phone numbers are never stored (N9); Claude vision has a 15 s timeout and falls back
to "type it instead" (N11).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from hound.chain import CacheMiss, ChainAPIError

log = logging.getLogger("hound.intake")
router = APIRouter()

SESSIONS: dict[str, dict[str, Any]] = {}
_ACTIVE: list[str] = []  # most recent case code last
_LOCK = threading.Lock()
TTL_S = 2 * 60 * 60
VISION_MODEL = os.environ.get("HOUND_VISION_MODEL", "claude-sonnet-5-5")
VISION_TIMEOUT_S = 15
VISION_MAX_TOKENS = 800
VISION_MIMES = ("image/png", "image/jpeg", "image/webp", "image/gif")
AMOUNT_TOL = 0.005  # ±0.5% (AUDIT N7)
TIME_WINDOW = timedelta(hours=2)
NO_TIME_WINDOW = timedelta(days=30)  # no time given: look back this far (still one get_transfers call)
LOCAL_TZ = ZoneInfo("America/Los_Angeles")  # a victim's naive "14:32" is their wall clock, not UTC
DATE_TIME = re.compile(r"(20\d\d-\d\d-\d\d(?:[T ]\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:Z|[+-]\d\d:?\d\d)?)?)")
CLOCK = re.compile(r"(?<![\d.])\d{1,2}:\d\d(?::\d\d)?(?![\d])")

TX_HASH = re.compile(r"0x[0-9a-fA-F]{64}")
# Not inside a longer hex run: a 64-hex tx hash starts with a 40-hex run that is not an address.
ETH_ADDR = re.compile(r"0x[0-9a-fA-F]{40}(?![0-9a-fA-F])")
TRUNC = re.compile(r"(0x[0-9a-fA-F]{3,12})\s*(?:…|\.\.\.+|\*+)\s*([0-9a-fA-F]{3,12})")
# Hashes and addresses are blanked before the amount scan (extract_from_text), so digits at the end
# of one ("...ab1234 USDT") are never an amount, while "Amount11,082.48" still reads 11082.48.
AMOUNT = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(USDT|USDⓈ|Tether|ETH)?", re.I)
# Phone-shaped runs only: digits with phone separators (space . - parentheses), optional +country.
# _scrub_phones then keeps anything with fewer than 10 digits, plain decimals and ISO dates, so
# "sent 11,082.48 USDT on 2026-10-15" survives while "+1 (415) 555-0134" is removed (AUDIT N9).
PHONE = re.compile(r"(?<![\w.,+])\+?\(?\d[\d\s().-]{6,}\d(?![\w,]|\.\d)")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
DECIMAL = re.compile(r"\d+\.\d+")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _public_base() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "http://localhost:3000").rstrip("/")


def _new_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I: read out loud on the phone
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        if code not in SESSIONS:
            return code


def _scrub(obj: Any) -> Any:
    """Drop phone numbers and caller ids anywhere in the payload (AUDIT N9)."""
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items() if k.lower() not in {"caller", "from_number", "phone", "caller_id", "to_number"}}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    if isinstance(obj, str):
        return PHONE.sub(_phone_or_keep, obj)
    return obj


def _phone_or_keep(m: re.Match) -> str:
    s = m.group(0)
    digits = sum(c.isdigit() for c in s)
    if not 10 <= digits <= 15 or ISO_DATE.search(s) or DECIMAL.fullmatch(s.strip()):
        return s
    return "[number removed]"


def _session_view(s: dict[str, Any]) -> dict[str, Any]:
    """The IntakeSession shape web/src/lib/types.ts expects."""
    v = {k: s.get(k) for k in ("case_code", "upload_url", "status", "story", "victim", "case_id", "message")}
    v["approved"] = bool(s.get("approved"))  # web shows the operator's Approve button state
    return v


def _authorised(request: Request) -> bool:
    """Cartesia tool calls carry X-Hound-Intake-Token; local callers (demo button, tests) are trusted."""
    from hound import api as hound_api  # lazy: api imports this module at startup
    if hound_api.token_matches(request.headers.get("x-hound-intake-token"), os.environ.get("HOUND_INTAKE_TOKEN")):
        return True
    return hound_api._is_local(request)


def reset() -> None:
    """/demo/reset: forget every intake session, so the next caller never sees the previous one."""
    with _LOCK:
        n = len(SESSIONS)
        SESSIONS.clear()
        _ACTIVE.clear()
    log.warning("intake reset: %d session(s) cleared", n)


def _expire() -> None:
    cutoff = time.time() - TTL_S
    for code in list(SESSIONS):
        if SESSIONS[code]["_created"] < cutoff:
            SESSIONS.pop(code, None)
            if code in _ACTIVE:
                _ACTIVE.remove(code)


def open_session(story: dict[str, Any] | None, victim: dict[str, Any] | None) -> dict[str, Any]:
    with _LOCK:
        _expire()
        code = _new_code()
        s = {"case_code": code, "upload_url": f"{_public_base()}/c/{code}", "status": "awaiting_upload",
             "story": _scrub(story or {}), "victim": _scrub(victim or {}), "case_id": None, "message": None,
             "_created": time.time()}
        SESSIONS[code] = s
        _ACTIVE.append(code)
    log.info("intake session %s opened", code)
    return s


def _tool_arg(body: dict[str, Any], key: str) -> Any:
    """body[key], or the same key under args / arguments / parameters (Cartesia may wrap tool args,
    sometimes as a JSON string)."""
    if key in body:
        return body[key]
    for wrap in ("args", "arguments", "parameters"):
        inner = body.get(wrap)
        if isinstance(inner, str):
            try:
                inner = json.loads(inner)
            except json.JSONDecodeError:
                continue
        if isinstance(inner, dict) and key in inner:
            log.info("intake voice tool: %r found under %r", key, wrap)
            return inner[key]
    log.warning("intake voice tool: no %r in the tool call body", key)
    return None


# ---------- routes ----------

@router.post("/intake/voice/story")
async def voice_story(request: Request):
    """Cartesia agent tool: the story is collected, open the upload session and give the agent the
    case code + link to read out. Body: {story:{scam_app,platform,first_contact,summary}, victim:{alias,age_band,exchange_used}}."""
    if not _authorised(request):
        raise HTTPException(403, "intake token required")
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(422, "body must be a JSON object")
    log.info("intake voice tool call: body keys %s", sorted(body.keys()))
    s = open_session(_tool_arg(body, "story"), _tool_arg(body, "victim"))
    spoken = " ".join(s["case_code"])  # "K 7 M 2 P Q" reads better than "K7M2PQ"
    return {"case_code": s["case_code"], "upload_url": s["upload_url"],
            "say": f"I have opened case {spoken}. The Hound team will help you open a short web page with this case code, where you can add a picture of the payment screen or type in the details."}


@router.post("/intake/start")
async def start_session(request: Request):
    """Demo / manual start (local only): same as the voice tool without a phone call."""
    if not _authorised(request):
        raise HTTPException(403, "local only")
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    s = open_session((body or {}).get("story"), (body or {}).get("victim"))
    return _session_view(s)


def _public_view(s: dict[str, Any]) -> dict[str, Any]:
    """What a non-operator sees: progress only. The case code and link are only read out to the
    caller on the phone and shown on the operator's (localhost) screen, never to a remote viewer."""
    v = _session_view(s)
    v["case_code"] = "••••••"
    v["upload_url"] = None
    v["story"] = None
    v["victim"] = None
    return v


@router.get("/intake/active")
def active(request: Request):
    """The most recent live session, or 204 when no call is in progress (web polls this every second).
    Operator (localhost or intake token) gets the full session; anyone else gets progress only."""
    full = _authorised(request)
    with _LOCK:
        _expire()
        # Newest first: the first session still in progress, or validated in the last 120 s (kept
        # visible for the reveal). An older stale session must never hide a newer validated one.
        for code in reversed(_ACTIVE):
            s = SESSIONS.get(code)
            if s and (s["status"] != "validated" or time.time() - s.get("_validated_at", 0) < 120):
                return _session_view(s) if full else _public_view(s)
    return Response(status_code=204)


@router.get("/intake/{case_code}")
def session(case_code: str, request: Request):
    """The upload page knows the code already; it gets status + message only unless the caller is the operator."""
    s = SESSIONS.get(case_code.upper())
    if not s:
        raise HTTPException(404, "unknown case code")
    return _session_view(s) if _authorised(request) else {"case_code": s["case_code"], "status": s["status"], "message": s.get("message")}


@router.post("/intake/{case_code}/approve")
async def approve(case_code: str, request: Request):
    """Operator step (localhost or intake token): the on-chain check proves the payment exists, not
    that the caller made it. Only after a human confirms does the case feed the watchlist.
    Body {"case_id": "..."} must name the case the operator actually reviewed."""
    from hound import api as hound_api
    hound_api.reject_cross_site(request, "POST /intake/approve")
    if not _authorised(request):
        raise HTTPException(403, "operator only")
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    wanted = (body or {}).get("case_id")
    with _LOCK:
        s = SESSIONS.get(case_code.upper())
        if not s or s["status"] != "validated" or not s.get("case_id"):
            raise HTTPException(409, "no validated case to approve")
        if not wanted or wanted != s["case_id"]:
            raise HTTPException(409, f"approve must name the reviewed case_id ({s['case_id']})")
        s["approved"] = True
    # Outside the intake lock: _register rebuilds the watchlist and writes a file.
    await run_in_threadpool(hound_api.mark_verified, s["case_id"])
    log.info("intake %s approved by operator -> case %s trusted", s["case_code"], s["case_id"])
    return {"status": "approved", "case_id": s["case_id"]}


@router.post("/intake/{case_code}/screenshot")
async def upload(case_code: str, request: Request, file: UploadFile | None = File(default=None), typed: str | None = Form(default=None)):
    code = case_code.upper()
    s = SESSIONS.get(code)
    if not s:
        raise HTTPException(404, "unknown case code")
    if not file and not (typed and typed.strip()):
        raise HTTPException(422, "send a screenshot as `file` or the details as `typed`")
    with _LOCK:  # atomic check-and-set: one upload at a time per session, none after validation
        if s["status"] == "validated":
            raise HTTPException(409, "this case already has a validated payment")
        if s["status"] == "validating":
            raise HTTPException(409, "an upload for this case is already being checked")
        s["status"] = "validating"
    try:
        if typed and typed.strip():
            extracted = extract_from_text(typed)
            extracted["source"] = "screenshot"  # typed-in details on the upload page count as the screenshot channel
        else:
            data = await file.read()
            if len(data) > 8 * 1024 * 1024:
                return _retake(s, "That image is too large. Please send a smaller screenshot, or type the details.")
            extracted = await run_in_threadpool(extract_from_image, data, _image_mime(data, file.content_type))
            extracted["source"] = "screenshot"
        case = await run_in_threadpool(validate_and_build_case, s, extracted)  # chain reads block
    except NeedsRetake as e:
        return _retake(s, str(e))
    except (CacheMiss, ChainAPIError) as e:  # offline cache miss or chain APIs down: not the victim's fault
        log.warning("intake %s: chain unreachable while validating: %s", code, type(e).__name__, exc_info=True)
        return _retake(s, CHAIN_DOWN_MSG)
    except Exception as e:  # noqa: BLE001 - never 500 at the victim; log and ask again
        log.exception("intake %s failed", code)
        return _retake(s, "We could not read that. Please try another screenshot, or type the transaction hash.")
    from hound import api as hound_api
    with _LOCK:
        if case["case_id"] in hound_api.CASES:
            s["status"] = "needs_retake"
            raise HTTPException(409, "case id collision; retry")
        hound_api.CASES[case["case_id"]] = case
        hound_api.LIVE_CASES.add(case["case_id"])  # a real victim's addresses: redacted beyond localhost
    # Not mark_verified here: the chain proves the payment exists, not that this caller made it.
    # A stranger's public tx must never put its recipient on the watchlist. POST /intake/{code}/approve
    # (operator only) promotes the case after a human look.
        s.update({"status": "validated", "case_id": case["case_id"], "message": None, "_validated_at": time.time()})
    log.info("intake %s validated -> case %s", code, case["case_id"])
    return {"status": "validated", "case_id": case["case_id"]}


def _retake(s: dict[str, Any], message: str) -> dict[str, Any]:
    s["status"] = "needs_retake"
    s["message"] = message
    return {"status": "needs_retake", "message": message}


class NeedsRetake(Exception):
    pass


# ---------- extraction ----------

def extract_from_text(text: str) -> dict[str, Any]:
    """Pull {tx_hash | to | to_prefix/suffix, amount, token, time} out of typed or OCR'd text."""
    out: dict[str, Any] = {"raw": text[:2000]}
    m = TX_HASH.search(text)
    if m:
        out["tx_hash"] = m.group(0).lower()
    addrs = [a.lower() for a in ETH_ADDR.findall(text)]
    if addrs:
        out["to"] = addrs[-1]
    t = TRUNC.search(text)
    if t and not addrs:
        out["to_prefix"], out["to_suffix"] = t.group(1).lower(), t.group(2).lower()
    best = None
    untokened = None
    # dates and clock times are blanked too, so "2026-10-15" or "14:32" never reads as an amount
    scan = CLOCK.sub(" ", DATE_TIME.sub(" ", TRUNC.sub(" ", ETH_ADDR.sub(" ", TX_HASH.sub(" ", text)))))
    for am in AMOUNT.finditer(scan):
        val = float(am.group(1).replace(",", ""))
        tok = (am.group(2) or "").upper()
        if tok in ("USDT", "TETHER", "USDⓈ"):
            tok = "USDT"
        if tok and (best is None or val > best[0]):
            best = (val, tok)
        if not tok and val > 0 and (untokened is None or val > untokened):
            untokened = val
    if best:
        out["amount"], out["token"] = best
    elif untokened is not None:
        out["amount"], out["token"] = untokened, "USDT"  # no token word: USDT is what victims send
        log.info("intake: amount %s had no token word; reading it as USDT", untokened)
    d = DATE_TIME.search(text)
    if d:
        out["time"] = d.group(1).replace(" ", "T")
    return out


def _image_mime(data: bytes, declared: str | None) -> str:
    """The real image type from its magic bytes (phones mislabel HEIC and friends); else the declared one."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    d = (declared or "").lower().strip()
    return "image/jpeg" if d == "image/jpg" else d or "application/octet-stream"


def extract_from_image(data: bytes, mime: str) -> dict[str, Any]:
    """Claude vision reads an exchange withdrawal or wallet send screen. 15 s cap, else retake (N11)."""
    if mime not in VISION_MIMES:
        log.info("intake image rejected: unsupported type %r", mime)
        raise NeedsRetake("Please send a PNG or JPEG screenshot, or type the transaction hash or the address you sent to.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise NeedsRetake("Image reading is unavailable right now. Please type the transaction hash or the address you sent to.")
    try:
        import anthropic
        client = anthropic.Anthropic(timeout=VISION_TIMEOUT_S, max_retries=0)
        prompt = ("This is a screenshot of a cryptocurrency payment (an exchange withdrawal detail page or a wallet send). "
                  "Extract ONLY what is visible. Reply with JSON and nothing else: "
                  '{"tx_hash": "0x... or null", "to": "destination address, full if visible, else the visible prefix and suffix like 0x2f1c…8fa4, or null", '
                  '"amount": number or null, "token": "USDT|ETH|other|null", "time": "ISO 8601 or the visible date text, or null", "chain": "ethereum|tron|null"}')
        # thinking "between_tools": no up-front thinking pass, so the budget goes to the JSON. With the
        # default, thinking ate all 300 tokens and every real screenshot came back empty ("retake").
        # ("disabled" is a 400 on this model.)
        msg = client.messages.create(model=VISION_MODEL, max_tokens=VISION_MAX_TOKENS, thinking={"type": "between_tools"},
                                     messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(data).decode()}},
            {"type": "text", "text": prompt}]}])
        text = "".join(getattr(b, "text", "") or "" for b in msg.content if getattr(b, "type", "text") == "text")
        if not text.strip():
            log.warning("vision returned no text (stop_reason=%s, max_tokens=%d)", getattr(msg, "stop_reason", None), VISION_MAX_TOKENS)
    except NeedsRetake:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("vision failed: %s", type(e).__name__)
        raise NeedsRetake("We could not read the image in time. Please type the transaction hash or the address you sent to.")
    j = re.search(r"\{.*\}", text, re.S)
    try:
        parsed = json.loads(j.group(0)) if j else {}
    except json.JSONDecodeError:
        parsed = {}
    out = extract_from_text(json.dumps(parsed) + "\n" + text)
    for k in ("amount", "token", "time", "chain"):
        if parsed.get(k) not in (None, "", "null"):
            out[k] = parsed[k]
    if isinstance(out.get("token"), str):
        out["token"] = out["token"].upper()
    out["vision"] = parsed
    return out


# ---------- on-chain validation ----------

def _iso(ts: str) -> datetime | None:
    """ISO time -> aware UTC datetime. A naive time is the victim's local clock (America/Los_Angeles)."""
    try:
        d = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None
    return (d if d.tzinfo else d.replace(tzinfo=LOCAL_TZ)).astimezone(timezone.utc)


def _search_window(ts: Any) -> tuple[str, str]:
    """(after, before) in UTC ISO for the address+amount search: ±2 h around a given time, the whole
    local day (±2 h) for a bare date, else the last 30 days. Width never changes the call count."""
    raw = str(ts or "").strip()
    when = _iso(raw)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    if when is None:
        if raw:
            log.info("intake: unreadable time %r; searching the last %d days", raw[:40], NO_TIME_WINDOW.days)
        now = datetime.now(timezone.utc)
        return (now - NO_TIME_WINDOW).strftime(fmt), now.strftime(fmt)
    if re.fullmatch(r"\d{4}-\d\d-\d\d", raw):
        return (when - TIME_WINDOW).strftime(fmt), (when + timedelta(days=1) + TIME_WINDOW).strftime(fmt)
    return (when - TIME_WINDOW).strftime(fmt), (when + TIME_WINDOW).strftime(fmt)


CHAIN_DOWN_MSG = "We couldn't reach the blockchain right now. Please try again in a minute."


def _rpc_outage(e: BaseException) -> bool:
    """tx_sends turns 'every RPC failed' into ValueError. It is a real not-found only when every RPC
    answered null for the tx; any other per-RPC error (timeout, 5xx, rate limit) means we could not look."""
    cause = e.__cause__
    if not isinstance(cause, (ChainAPIError, CacheMiss)):
        return False
    if isinstance(cause, CacheMiss):
        return True
    parts = str(cause).split(": ", 1)[-1].split(" | ")
    return not all("null result" in p for p in parts)


def validate_and_build_case(s: dict[str, Any], ex: dict[str, Any]) -> dict[str, Any]:
    """Confirm the send exists on chain and build a schema-valid Case (source: screenshot).
    Accepts: a full tx hash (receipt read, amount cross-checked when given), or a destination
    address (full, or prefix…suffix) + amount, matched ±0.5% within ±2 h of the given time
    (naive = America/Los_Angeles; no time = the last 30 days)."""
    from hound import chain
    from hound.contracts import validate_case
    sends: list[dict[str, Any]] = []
    if ex.get("tx_hash"):
        try:
            sends = chain.tx_sends("ethereum", ex["tx_hash"])
        except ValueError as e:
            if _rpc_outage(e):
                log.warning("intake %s: RPCs unreachable while reading the typed tx hash", s.get("case_code"), exc_info=True)
                raise NeedsRetake(CHAIN_DOWN_MSG)
            log.info("intake %s: tx hash did not check out: %s", s.get("case_code"), e)
            raise NeedsRetake("That transaction hash did not check out on Ethereum. Please check it and try again.")
        if ex.get("amount") and sends:
            close = [x for x in sends if abs(float(x["amount"]) - float(ex["amount"])) <= AMOUNT_TOL * float(ex["amount"])]
            if not close:
                raise NeedsRetake("That hash is real, but the amount on screen does not match what the chain shows. Please double-check the screenshot.")
    elif (ex.get("to") or ex.get("to_prefix")) and ex.get("amount"):
        lo, hi = _search_window(ex.get("time"))
        if ex.get("to"):
            rows = chain.get_transfers("ethereum", ex["to"], token="USDT" if ex.get("token", "USDT") != "ETH" else "ETH", after=lo, before=hi)
            rows = [r for r in rows if r["to"].lower() == ex["to"]]
        else:
            raise NeedsRetake("Please type the full destination address (0x and 40 characters) or the transaction hash; a shortened address is not enough to find the payment.")
        amt = float(ex["amount"])
        hits = [r for r in rows if abs(float(r["amount"]) - amt) <= AMOUNT_TOL * amt]
        if len(hits) != 1:
            raise NeedsRetake(f"We found {len(hits)} payments of about {amt:,.2f} to that address in that time window; we need exactly one. Please send the transaction hash instead.")
        r = hits[0]
        sends = [{"chain": "ethereum", "tx_hash": r["tx_hash"], "from": r["from"].lower(), "to": r["to"].lower(), "token": r.get("token", "USDT"), "amount": float(r["amount"]), "time": r["time"]}]
    else:
        raise NeedsRetake("We need the transaction hash, or the address you sent to plus the amount. Please type them in.")
    if not sends:
        raise NeedsRetake("No payment by you was found in that transaction. Please check the hash.")
    case = {"case_id": f"intake-{s['case_code'].lower()}-{secrets.token_hex(3)}", "created_at": _now(), "source": "screenshot",
            "victim": {"alias": (s.get("victim") or {}).get("alias") or f"Caller, case {s['case_code']}",
                       "age_band": (s.get("victim") or {}).get("age_band"), "exchange_used": (s.get("victim") or {}).get("exchange_used")},
            "story": {k: (s.get("story") or {}).get(k) for k in ("scam_app", "platform", "first_contact", "summary")},
            "sends": [{k: x[k] for k in ("chain", "tx_hash", "from", "to", "token", "amount", "time")} for x in sends],
            "status": "intake", "freeze_visibility": "visible", "data_cutoff_block": None, "as_of": None}
    validate_case(case)
    return case
