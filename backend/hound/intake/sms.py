"""Text the caller their upload link right after the voice agent opens the case.

Sends through Twilio when TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER are set; otherwise
nothing is sent and the agent reads the link's case code out instead. Cartesia has no SMS of its own; the
caller's number comes from its system__caller_id variable. The number is never stored in the session or
logged beyond its last 2 digits.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
from collections import deque
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("hound.intake.sms")

# Every text costs money and a leaked intake token must not turn into an SMS cannon: one text per number
# per 10 minutes, and at most 20 an hour in total.
PER_NUMBER_S = 600
PER_HOUR = 20
_LOCK = threading.Lock()
_LAST: dict[str, float] = {}
_RECENT: deque[float] = deque()


def _allow(to: str) -> bool:
    now = time.monotonic()
    with _LOCK:
        while _RECENT and now - _RECENT[0] > 3600:
            _RECENT.popleft()
        if now - _LAST.get(to, -PER_NUMBER_S) < PER_NUMBER_S or len(_RECENT) >= PER_HOUR:
            return False
        _LAST[to] = now
        _RECENT.append(now)
        return True


def _mask(text: str) -> str:
    """Twilio errors echo the To number; keep phone-length digit runs out of the log."""
    return re.sub(r"\+?\d[\d\s().-]{6,}\d", "<number>", text)


def normalize(number: str | None) -> str | None:
    """+1XXXXXXXXXX for a US number, +<digits> for another international one, None if it isn't a phone number."""
    if not number or not isinstance(number, str):
        return None
    digits = re.sub(r"\D", "", number)
    if number.strip().startswith("+") and 8 <= len(digits) <= 15:
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return None


def _creds() -> tuple[str, str, str] | None:
    sid, token, sender = (os.environ.get(k, "").strip() for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"))
    return (sid, token, sender) if sid and token and sender else None


def enabled() -> bool:
    return _creds() is not None


def send_link(number: str | None, url: str, code: str) -> bool:
    """True when Twilio accepted the text. Never raises: the call goes on with the spoken fallback."""
    creds, to = _creds(), normalize(number)
    if not creds:
        return False
    if not to:
        log.warning("sms: no usable caller number for case %s, not texting", code)
        return False
    if not _allow(to):
        log.warning("sms: rate limit, not texting case %s to ..%s", code, to[-2:])
        return False
    sid, token, sender = creds
    body = f"Hound: your case code is {code}. Open this link to send a picture of your payment: {url}"
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", method="POST",
        data=urllib.parse.urlencode({"To": to, "From": sender, "Body": body}).encode(),
        headers={"Authorization": "Basic " + base64.b64encode(f"{sid}:{token}".encode()).decode()})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            status = json.loads(r.read()).get("status")
    except urllib.error.HTTPError as e:
        detail = _mask(e.read().decode(errors="replace")[:300])
        log.error("sms: Twilio refused case %s to ..%s: HTTP %s %s", code, to[-2:], e.code, detail)
        return False
    except (OSError, ValueError) as e:
        log.error("sms: Twilio unreachable for case %s to ..%s: %s", code, to[-2:], _mask(str(e)))
        return False
    # "queued" means accepted, not delivered: a blocked number (e.g. 30034, unregistered 10DLC) fails later in Twilio's log.
    log.info("sms: case %s link accepted by Twilio for ..%s (status %s)", code, to[-2:], status)
    return True
