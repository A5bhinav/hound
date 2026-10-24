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
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("hound.intake.sms")


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
        detail = e.read().decode(errors="replace")[:300]
        log.error("sms: Twilio refused case %s to ..%s: HTTP %s %s", code, to[-2:], e.code, detail)
        return False
    except (OSError, ValueError) as e:
        log.error("sms: Twilio unreachable for case %s to ..%s: %s", code, to[-2:], e)
        return False
    # "queued" means accepted, not delivered: a blocked number (e.g. 30034, unregistered 10DLC) fails later in Twilio's log.
    log.info("sms: case %s link accepted by Twilio for ..%s (status %s)", code, to[-2:], status)
    return True
