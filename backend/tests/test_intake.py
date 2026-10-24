import io

from fastapi.testclient import TestClient

import hound.api as api
from hound.intake import routes as intake

client = TestClient(api.app, client=("127.0.0.1", 50001))
TX = "0x" + "ab" * 32


def _fake_tx_sends(chain, tx_hash, to=None, sender=None):
    assert chain == "ethereum" and tx_hash == TX
    return [{"chain": "ethereum", "tx_hash": TX, "from": "0x" + "1" * 40, "to": "0x" + "2" * 40, "token": "USDT",
             "amount": 11082.48, "time": "2026-10-15T12:00:00Z"}]


def setup_function():
    intake.SESSIONS.clear()
    intake._ACTIVE.clear()


def test_active_is_204_without_session():
    assert client.get("/intake/active").status_code == 204


def test_story_opens_session_and_scrubs_phone_numbers():
    r = client.post("/intake/voice/story", json={"story": {"scam_app": "MindChainSwap", "summary": "call me at +1 (415) 555-0100"},
                                                "victim": {"alias": "Caller"}, "caller": "+14155550100"})
    assert r.status_code == 200
    code = r.json()["case_code"]
    assert len(code) == 6 and r.json()["upload_url"].endswith(f"/c/{code}") and "say" in r.json()
    a = client.get("/intake/active").json()
    assert a["case_code"] == code and a["status"] == "awaiting_upload"
    assert "555" not in a["story"]["summary"] and "caller" not in a


def test_typed_hash_validates_on_chain_and_marks_verified(monkeypatch):
    import hound.chain as chain
    monkeypatch.setattr(chain, "tx_sends", _fake_tx_sends)
    code = client.post("/intake/start", json={}).json()["case_code"]
    r = client.post(f"/intake/{code}/screenshot", data={"typed": f"I sent 11,082.48 USDT, hash {TX}"})
    assert r.status_code == 200 and r.json()["status"] == "validated", r.json()
    cid = r.json()["case_id"]
    assert cid in api.CASES and cid not in api.TRUSTED  # chain-confirmed, not yet operator-approved
    assert api.CASES[cid]["sends"][0]["amount"] == 11082.48 and api.CASES[cid]["source"] == "screenshot"
    assert client.get("/intake/active").json()["status"] == "validated"
    # second upload on a validated session is refused, case never overwritten
    assert client.post(f"/intake/{code}/screenshot", data={"typed": TX}).status_code == 409
    # operator approval is what makes it trusted
    assert client.post(f"/intake/{code}/approve", json={"case_id": "intake-wrong"}).status_code == 409
    # CSRF: another site cannot drive the operator's browser into approving
    assert client.post(f"/intake/{code}/approve", json={"case_id": cid}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post(f"/intake/{code}/approve", json={"case_id": cid}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert cid not in api.TRUSTED
    assert client.post(f"/intake/{code}/approve", json={"case_id": cid}, headers={"Origin": "http://localhost:3000"}).json()["status"] == "approved" and cid in api.TRUSTED
    remote = TestClient(api.app, client=("203.0.113.9", 40000))
    assert remote.post(f"/intake/{code}/approve", json={"case_id": cid}).status_code == 403


def test_amount_mismatch_asks_for_retake(monkeypatch):
    import hound.chain as chain
    monkeypatch.setattr(chain, "tx_sends", _fake_tx_sends)
    code = client.post("/intake/start", json={}).json()["case_code"]
    r = client.post(f"/intake/{code}/screenshot", data={"typed": f"sent 500 USDT hash {TX}"})
    assert r.json()["status"] == "needs_retake" and "amount" in r.json()["message"]
    assert not any(c.startswith(f"intake-{code.lower()}") for c in api.TRUSTED)


def test_bad_hash_is_a_retake_not_a_500(monkeypatch):
    import hound.chain as chain
    monkeypatch.setattr(chain, "tx_sends", lambda *a, **k: (_ for _ in ()).throw(ValueError("failed tx")))
    code = client.post("/intake/start", json={}).json()["case_code"]
    r = client.post(f"/intake/{code}/screenshot", data={"typed": "0x" + "cd" * 32})
    assert r.status_code == 200 and r.json()["status"] == "needs_retake"


def test_image_without_vision_key_falls_back_to_typing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = client.post("/intake/start", json={}).json()["case_code"]
    r = client.post(f"/intake/{code}/screenshot", files={"file": ("shot.png", io.BytesIO(b"\x89PNG not really"), "image/png")})
    assert r.json()["status"] == "needs_retake" and "type" in r.json()["message"].lower()


def test_story_requires_token_or_localhost():
    remote = TestClient(api.app, client=("203.0.113.9", 40000))
    assert remote.post("/intake/voice/story", json={}).status_code == 403


def test_remote_viewer_never_sees_case_code_or_link():
    client.post("/intake/start", json={"story": {"summary": "secret story"}}).json()
    remote = TestClient(api.app, client=("203.0.113.9", 40000))
    v = remote.get("/intake/active").json()
    assert v["case_code"] == "••••••" and v["upload_url"] is None and v["story"] is None and v["status"] == "awaiting_upload"
    local = client.get("/intake/active").json()
    assert len(local["case_code"]) == 6 and local["upload_url"].endswith(local["case_code"])


def test_extract_from_text_handles_truncated_address_and_amount():
    ex = intake.extract_from_text("Sent 96,028.85 USDT to 0x2f1c…8fa4 on 2026-10-08 15:45")
    assert ex["amount"] == 96028.85 and ex["token"] == "USDT" and ex["to_prefix"] == "0x2f1c" and ex["to_suffix"] == "8fa4" and ex["time"].startswith("2026-10-08")


def test_concurrent_upload_refused_while_validating():
    code = client.post("/intake/start", json={}).json()["case_code"]
    intake.SESSIONS[code]["status"] = "validating"
    assert client.post(f"/intake/{code}/screenshot", data={"typed": TX}).status_code == 409


def _poll_done(job_id, timeout=10):
    import time
    end = time.time() + timeout
    while time.time() < end:
        body = client.get(f"/traces/{job_id}").json()
        if body.get("status") != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("trace never finished")


def test_approve_after_trace_feeds_the_watchlist_without_a_retrace(monkeypatch):
    """The operator reviews the trace, then approves: that approval must register the trace it saw
    (before, approval only added the id to TRUSTED and the reviewed trace never reached /check)."""
    import hound.chain as chain
    monkeypatch.setattr(chain, "tx_sends", _fake_tx_sends)
    registered = []
    monkeypatch.setattr(api, "register_trace", lambda trace: registered.append(trace["case_id"]) or 0)
    code = client.post("/intake/start", json={}).json()["case_code"]
    cid = client.post(f"/intake/{code}/screenshot", data={"typed": f"hash {TX} 11,082.48 USDT"}).json()["case_id"]
    trace = _poll_done(client.post(f"/cases/{cid}/trace").json()["trace_id"])
    assert trace["status"] in ("done", "partial")
    assert cid not in registered, "a validated but unapproved intake case must not feed the watchlist"
    assert client.post(f"/intake/{code}/approve", json={"case_id": cid}).json()["status"] == "approved"
    assert registered == [cid]
    api.TRUSTED.discard(cid)


def test_approve_before_trace_registers_on_the_trace(monkeypatch):
    import hound.chain as chain
    monkeypatch.setattr(chain, "tx_sends", _fake_tx_sends)
    registered = []
    monkeypatch.setattr(api, "register_trace", lambda trace: registered.append(trace["case_id"]) or 0)
    code = client.post("/intake/start", json={}).json()["case_code"]
    cid = client.post(f"/intake/{code}/screenshot", data={"typed": f"hash {TX} 11,082.48 USDT"}).json()["case_id"]
    assert client.post(f"/intake/{code}/approve", json={"case_id": cid}).json()["status"] == "approved"
    assert registered == []  # nothing traced yet, nothing to register
    _poll_done(client.post(f"/cases/{cid}/trace").json()["trace_id"])
    assert registered == [cid]
    api.TRUSTED.discard(cid)


def test_tx_hash_is_not_read_as_an_address_or_amount():
    """A 64-hex hash contains a 40-hex run; that must never become the destination address, and
    digits at the end of a hash must never become the amount."""
    h = "0x" + "ab" * 30 + "1234"
    ex = intake.extract_from_text(f"tx {h} USDT")
    assert ex["tx_hash"] == h and "to" not in ex and "amount" not in ex
    to = "0x" + "2f" * 20
    ex = intake.extract_from_text(f"sent 500 USDT to {to}, tx {h}")
    assert ex["to"] == to and ex["amount"] == 500 and ex["token"] == "USDT"


def test_unreachable_chain_says_so_instead_of_could_not_read(monkeypatch):
    """Offline (readonly cache miss) or chain API down: the victim is told the check could not run,
    not that their screenshot was unreadable."""
    import hound.chain as chain
    monkeypatch.setattr(chain, "tx_sends", lambda *a, **k: (_ for _ in ()).throw(chain.CacheMiss("readonly")))
    code = client.post("/intake/start", json={}).json()["case_code"]
    r = client.post(f"/intake/{code}/screenshot", data={"typed": TX})
    assert r.status_code == 200 and r.json()["status"] == "needs_retake"
    assert "reach the blockchain" in r.json()["message"]


def test_amount_glued_to_a_word_still_reads_whole():
    """Typed or OCR text with a missing space: the whole number is the amount, not its tail."""
    assert intake.extract_from_text("Amount11,082.48 USDT")["amount"] == 11082.48
    assert intake.extract_from_text("金额11082.48USDT")["amount"] == 11082.48
    trunc = intake.extract_from_text("to 0xab12…cd3456 USDT, 300 USDT")
    assert trunc["amount"] == 300


def test_voice_say_line_never_promises_a_text_message():
    say = client.post("/intake/voice/story", json={"story": {}, "victim": {}}).json()["say"]
    assert "text" not in say.lower().replace("type in the details", "")


def _twilio_env(monkeypatch):
    for k, v in (("TWILIO_ACCOUNT_SID", "AC1"), ("TWILIO_AUTH_TOKEN", "t"), ("TWILIO_FROM_NUMBER", "+15550001111"),
                 ("HOUND_INTAKE_TOKEN", "tok")):
        monkeypatch.setenv(k, v)
    intake.sms._LAST.clear()
    intake.sms._RECENT.clear()


TOOL = {"X-Hound-Intake-Token": "tok"}


def test_voice_texts_the_link_through_twilio(monkeypatch):
    _twilio_env(monkeypatch)
    sent = []

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"status": "queued"}'

    def fake_urlopen(req, timeout):
        sent.append(req)
        return Resp()

    monkeypatch.setattr(intake.sms.urllib.request, "urlopen", fake_urlopen)
    body = {"story": {}, "victim": {}, "caller_number": "(415) 555-0134"}
    # local trust alone (no token header) never texts: a page in the operator's browser could forge that
    assert client.post("/intake/voice/story", json=body).json()["texted"] is False and not sent
    r = client.post("/intake/voice/story", json=body, headers=TOOL).json()
    assert r["texted"] is True and "walk you through" in r["say"]
    # the same number again within 10 minutes is not texted twice
    assert client.post("/intake/voice/story", json=body, headers=TOOL).json()["texted"] is False and len(sent) == 1
    form = sent[0].data.decode()
    assert "To=%2B14155550134" in form and r["case_code"] in form and sent[0].full_url.endswith("/AC1/Messages.json")
    # the number is never kept in the session the web reads
    assert "555" not in str(client.get("/intake/active").json())


def test_voice_falls_back_to_spoken_line_without_a_number_or_on_failure(monkeypatch):
    _twilio_env(monkeypatch)

    def refuse(req, timeout):
        raise intake.sms.urllib.error.HTTPError(req.full_url, 400, "bad", {}, io.BytesIO(b'{"code": 21211}'))

    monkeypatch.setattr(intake.sms.urllib.request, "urlopen", refuse)
    for body in ({"story": {}, "victim": {}}, {"story": {}, "victim": {}, "caller_number": "+14155550134"}):
        r = client.post("/intake/voice/story", json=body, headers=TOOL).json()
        assert r["texted"] is False and "Hound team will help" in r["say"]


def test_voice_status_tool_reports_upload_progress():
    code = client.post("/intake/voice/story", json={"story": {}, "victim": {}}).json()["case_code"]
    r = client.post("/intake/voice/status", json={"case_code": " ".join(code)}).json()
    assert r["status"] == "awaiting_upload" and "not arrived" in r["say"]
    intake.SESSIONS[code].update(status="needs_retake", message="We need the transaction hash.")
    assert "another picture" in client.post("/intake/voice/status", json={"args": {"case_code": code}}).json()["say"]
    assert client.post("/intake/voice/status", json={"case_code": "ZZZZZZ"}).json()["status"] == "unknown"
    remote = TestClient(api.app, client=("203.0.113.9", 1))
    assert remote.post("/intake/voice/status", json={"case_code": code}).status_code == 403


def test_sms_errors_never_log_the_number(monkeypatch, caplog):
    _twilio_env(monkeypatch)

    def refuse(req, timeout):
        raise intake.sms.urllib.error.HTTPError(req.full_url, 400, "bad", {}, io.BytesIO(
            b'{"message": "The \'To\' number +14155550134 is not a valid phone number."}'))

    monkeypatch.setattr(intake.sms.urllib.request, "urlopen", refuse)
    assert intake.sms.send_link("+14155550134", "https://x/c/ABC", "ABC") is False
    assert "4155550134" not in caplog.text and "<number>" in caplog.text


def test_sms_normalize():
    assert intake.sms.normalize("+1 415-555-0134") == "+14155550134"
    assert intake.sms.normalize("4155550134") == "+14155550134"
    assert intake.sms.normalize("+353 87 123 4567") == "+353871234567"
    assert intake.sms.normalize("anonymous") is None and intake.sms.normalize("") is None


def test_demo_reset_clears_intake_sessions():
    code = client.post("/intake/start", json={}).json()["case_code"]
    assert client.get("/intake/active").status_code == 200
    assert client.post("/demo/reset").status_code == 200
    assert client.get("/intake/active").status_code == 204
    assert client.get(f"/intake/{code}").status_code == 404


def test_intake_case_is_redacted_for_remote_viewers(monkeypatch):
    import hound.chain as chain
    monkeypatch.setattr(chain, "tx_sends", _fake_tx_sends)
    code = client.post("/intake/start", json={"story": {"summary": "my story"}}).json()["case_code"]
    cid = client.post(f"/intake/{code}/screenshot", data={"typed": f"11,082.48 USDT {TX}"}).json()["case_id"]
    assert cid in api.LIVE_CASES
    local = next(c for c in client.get("/cases").json() if c["case_id"] == cid)
    assert local["sends"][0]["tx_hash"] == TX
    remote = TestClient(api.app, client=("203.0.113.9", 40000))
    far = next(c for c in remote.get("/cases").json() if c["case_id"] == cid)
    assert far["sends"][0]["tx_hash"] != TX and "story" not in far
    api.CASES.pop(cid, None)
    api.LIVE_CASES.discard(cid)


class _FakeMessages:
    def __init__(self, text, stop_reason="end_turn"):
        self.calls, self.text, self.stop_reason = [], text, stop_reason

    def create(self, **kw):
        from types import SimpleNamespace
        self.calls.append(kw)
        blocks = [SimpleNamespace(type="thinking", thinking="hmm")]
        if self.text:
            blocks.append(SimpleNamespace(type="text", text=self.text))
        return SimpleNamespace(content=blocks, stop_reason=self.stop_reason)


def _fake_anthropic(monkeypatch, text, stop_reason="end_turn"):
    import anthropic
    msgs = _FakeMessages(text, stop_reason)
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: type("C", (), {"messages": msgs})())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    return msgs


PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def test_vision_call_skips_upfront_thinking_and_reads_the_json(monkeypatch):
    msgs = _fake_anthropic(monkeypatch, '{"tx_hash": "' + TX + '", "amount": 11082.48, "token": "usdt", "to": null}')
    ex = intake.extract_from_image(PNG, "image/png")
    kw = msgs.calls[0]
    assert kw["thinking"] == {"type": "between_tools"} and kw["max_tokens"] >= 600
    assert ex["tx_hash"] == TX and ex["amount"] == 11082.48 and ex["token"] == "USDT"


def test_vision_empty_text_at_max_tokens_is_logged(monkeypatch, caplog):
    _fake_anthropic(monkeypatch, "", stop_reason="max_tokens")
    with caplog.at_level("WARNING", logger="hound.intake"):
        ex = intake.extract_from_image(PNG, "image/png")
    assert "tx_hash" not in ex and any("max_tokens" in r.getMessage() for r in caplog.records)


def test_heic_upload_asks_for_png_or_jpeg(monkeypatch):
    msgs = _fake_anthropic(monkeypatch, "{}")
    code = client.post("/intake/start", json={}).json()["case_code"]
    heic = b"\0\0\0\x18ftypheic" + b"\0" * 32
    r = client.post(f"/intake/{code}/screenshot", files={"file": ("IMG_1.HEIC", io.BytesIO(heic), "image/heic")})
    assert r.json()["status"] == "needs_retake" and "PNG or JPEG" in r.json()["message"]
    assert msgs.calls == []  # never sent to Claude mislabeled as a PNG


def test_upload_and_approve_run_blocking_work_off_the_event_loop(monkeypatch):
    import threading
    seen = {}
    real_validate = intake.validate_and_build_case
    monkeypatch.setattr(intake, "validate_and_build_case",
                        lambda s, ex: seen.setdefault("validate", threading.current_thread().name) and real_validate(s, ex))
    monkeypatch.setattr(api, "mark_verified", lambda cid: seen.setdefault("approve", threading.current_thread().name))
    import hound.chain as chain
    monkeypatch.setattr(chain, "tx_sends", _fake_tx_sends)
    code = client.post("/intake/start", json={}).json()["case_code"]
    cid = client.post(f"/intake/{code}/screenshot", data={"typed": f"11,082.48 USDT {TX}"}).json()["case_id"]
    client.post(f"/intake/{code}/approve", json={"case_id": cid})
    assert "AnyIO worker" in seen["validate"] and "AnyIO worker" in seen["approve"], seen
    api.CASES.pop(cid, None)
    api.LIVE_CASES.discard(cid)


def test_older_open_session_never_hides_a_newer_validated_one(monkeypatch):
    import hound.chain as chain
    monkeypatch.setattr(chain, "tx_sends", _fake_tx_sends)
    client.post("/intake/start", json={})  # older call, never finished
    code = client.post("/intake/start", json={}).json()["case_code"]
    cid = client.post(f"/intake/{code}/screenshot", data={"typed": f"11,082.48 USDT {TX}"}).json()["case_id"]
    a = client.get("/intake/active").json()
    assert a["case_code"] == code and a["status"] == "validated" and a["approved"] is False
    client.post(f"/intake/{code}/approve", json={"case_id": cid})
    assert client.get("/intake/active").json()["approved"] is True
    intake.SESSIONS[code]["_validated_at"] -= 121  # reveal window over: the older open call shows again
    assert client.get("/intake/active").json()["case_code"] != code
    api.CASES.pop(cid, None)
    api.LIVE_CASES.discard(cid)
    api.TRUSTED.discard(cid)


def test_check_evidence_from_a_live_case_is_redacted_beyond_localhost(monkeypatch):
    from hound.watch import routes as watch_routes
    victim, scam = "0x" + "1" * 40, "0x" + "2" * 40
    fake = {"decision": "hold", "reasons": [f"paid by victim {victim}"], "confidence": 0.9,
            "evidence": {"case_ids": ["intake-abc123-ff"], "path": [{"from": victim, "to": scam, "tx_hash": TX}]}}
    monkeypatch.setattr(watch_routes, "check", lambda c, a: fake)
    local = client.get("/check", params={"chain": "ethereum", "address": scam}).json()
    assert local["evidence"]["path"][0]["tx_hash"] == TX
    remote = TestClient(api.app, client=("203.0.113.9", 40000))
    far = remote.get("/check", params={"chain": "ethereum", "address": scam}).json()
    hop = far["evidence"]["path"][0]
    assert far["decision"] == "hold" and hop["tx_hash"] != TX and victim not in hop["from"] and victim not in far["reasons"][0]
    fake["evidence"]["case_ids"] = ["curated-demo"]  # a curated replay case stays public
    assert remote.get("/check", params={"chain": "ethereum", "address": scam}).json()["evidence"]["path"][0]["tx_hash"] == TX


def _tx_sends_raising(msg):
    def boom(*a, **k):
        from hound.chain import ChainAPIError
        try:
            raise ChainAPIError(msg)
        except ChainAPIError as e:
            raise ValueError(f"tx not found on any RPC: {e}") from e
    return boom


def test_rpc_outage_on_typed_hash_says_try_again(monkeypatch):
    import hound.chain as chain
    monkeypatch.setattr(chain, "tx_sends", _tx_sends_raising(
        "every RPC failed for eth_getTransactionByHash: https://rpc-a 503 | https://rpc-b timed out"))
    code = client.post("/intake/start", json={}).json()["case_code"]
    msg = client.post(f"/intake/{code}/screenshot", data={"typed": TX}).json()["message"]
    assert "couldn't reach the blockchain" in msg and "rpc" not in msg.lower() and "503" not in msg


def test_hash_every_rpc_says_null_is_a_real_not_found(monkeypatch):
    import hound.chain as chain
    monkeypatch.setattr(chain, "tx_sends", _tx_sends_raising(
        "every RPC failed for eth_getTransactionByHash: https://rpc-a eth_getTransactionByHash: null result (pruned node?)"
        " | https://rpc-b eth_getTransactionByHash: null result (pruned node?)"))
    code = client.post("/intake/start", json={}).json()["case_code"]
    msg = client.post(f"/intake/{code}/screenshot", data={"typed": TX}).json()["message"]
    assert "did not check out" in msg and "null" not in msg and "rpc" not in msg.lower()


def test_voice_story_reads_wrapped_tool_args():
    import json
    story = {"scam_app": "MindChainSwap", "summary": "lost savings"}
    for body in ({"args": {"story": story, "victim": {"alias": "Ann"}}},
                 {"arguments": json.dumps({"story": story, "victim": {"alias": "Ann"}})},
                 {"parameters": {"story": story, "victim": {"alias": "Ann"}}}):
        intake.SESSIONS.clear()
        intake._ACTIVE.clear()
        assert client.post("/intake/voice/story", json=body).status_code == 200
        a = client.get("/intake/active").json()
        assert a["story"]["scam_app"] == "MindChainSwap" and a["victim"]["alias"] == "Ann", body


def test_jpeg_labelled_octet_stream_is_sniffed(monkeypatch):
    msgs = _fake_anthropic(monkeypatch, "{}")
    jpg = b"\xff\xd8\xff\xe0" + b"\0" * 16
    intake.extract_from_image(jpg, intake._image_mime(jpg, "application/octet-stream"))
    assert msgs.calls[0]["messages"][0]["content"][0]["source"]["media_type"] == "image/jpeg"


def test_scrub_keeps_amounts_and_dates_but_removes_phone_numbers():
    story = "sent 11,082.48 USDT on 2026-10-15 at 2026-10-15T14:32, then 500 more; call +1 (415) 555-0134"
    out = intake._scrub(story)
    assert "11,082.48 USDT on 2026-10-15" in out and "2026-10-15T14:32" in out and "500 more" in out
    assert "555" not in out and "[number removed]" in out
    for phone in ("+1 (415) 555-0134", "415-555-0134", "(415) 555 0134", "+44 20 7946 0958", "415.555.0134", "+14155550134"):
        assert intake._scrub(f"ring {phone} now") == "ring [number removed] now", phone
    for keep in ("1,250,000.00 USDT", "11082.48", "block 21000000", "2026-10-15 14:32", "0.25 ETH"):
        assert intake._scrub(f"x {keep} y") == f"x {keep} y", keep


TO = "0x" + "2" * 40


def _capture_transfers(monkeypatch, amount=500.0):
    import hound.chain as chain
    calls = []

    def fake(ch, address, token="USDT", after=None, before=None, **_):
        calls.append({"token": token, "after": after, "before": before})
        return [{"tx_hash": "0x" + "cd" * 32, "from": "0x" + "1" * 40, "to": address, "token": "USDT",
                 "amount": amount, "time": after}]
    monkeypatch.setattr(chain, "get_transfers", fake)
    return calls


def test_amount_without_token_word_is_usdt_and_dates_are_not_amounts():
    ex = intake.extract_from_text(f"on 2026-10-15 14:32 I sent 500 to {TO}")
    assert ex["amount"] == 500 and ex["token"] == "USDT" and ex["time"] == "2026-10-15T14:32"
    assert intake.extract_from_text(f"sent 0.25 ETH and 900 to {TO}")["token"] == "ETH"  # a token word wins
    assert "amount" not in intake.extract_from_text(f"2026-10-15 to {TO}")


def test_naive_time_is_los_angeles(monkeypatch):
    calls = _capture_transfers(monkeypatch)
    case = intake.validate_and_build_case({"case_code": "ABCDEF"}, intake.extract_from_text(f"sent 500 to {TO} at 2026-10-15 14:32"))
    # 14:32 PDT = 21:32 UTC, ±2 h
    assert calls == [{"token": "USDT", "after": "2026-10-15T19:32:00Z", "before": "2026-10-15T23:32:00Z"}]
    assert case["sends"][0]["amount"] == 500
    calls.clear()
    intake.validate_and_build_case({"case_code": "ABCDEF"}, intake.extract_from_text(f"sent 500 USDT to {TO} at 2026-10-15T14:32:00Z"))
    assert calls[0]["after"] == "2026-10-15T12:32:00Z"  # an explicit Z stays UTC


def test_no_time_searches_the_last_30_days(monkeypatch):
    from datetime import datetime, timedelta, timezone
    calls = _capture_transfers(monkeypatch)
    intake.validate_and_build_case({"case_code": "ABCDEF"}, intake.extract_from_text(f"sent 500 USDT to {TO}"))
    assert len(calls) == 1  # one chain call whatever the window
    after = datetime.fromisoformat(calls[0]["after"].replace("Z", "+00:00"))
    before = datetime.fromisoformat(calls[0]["before"].replace("Z", "+00:00"))
    assert before - after == timedelta(days=30) and abs(datetime.now(timezone.utc) - before) < timedelta(minutes=1)


def test_web_report_opens_a_session_and_is_rate_limited():
    intake._WEB_RECENT.clear()
    remote = TestClient(api.app, client=("203.0.113.7", 1))
    r = remote.post("/intake/web/start", json={"summary": "I sent 2,000 USDT to an investment app", "name": "Maria",
                                               "exchange_used": "Coinbase"})
    assert r.status_code == 200
    code = r.json()["case_code"]
    s = intake.SESSIONS[code]
    assert s["status"] == "awaiting_upload" and s["victim"]["alias"] == "Maria" and "2,000 USDT" in s["story"]["summary"]
    # the public view gives the code holder their case id and exchange, never the story or upload link
    view = remote.get(f"/intake/{code}").json()
    assert set(view) == {"case_code", "status", "message", "case_id", "exchange_used"} and view["exchange_used"] == "Coinbase"
    for _ in range(intake.WEB_PER_IP_HOUR - 1):
        assert remote.post("/intake/web/start", json={}).status_code == 200
    assert remote.post("/intake/web/start", json={}).status_code == 429
    other = TestClient(api.app, client=("203.0.113.8", 1))
    assert other.post("/intake/web/start", json={}).status_code == 200
    intake._WEB_RECENT.clear()


def test_case_code_unlocks_only_its_own_case():
    code = client.post("/intake/start", json={}).json()["case_code"]
    intake.SESSIONS[code].update(status="validated", case_id="intake-abc")
    assert intake.owns_case(code.lower(), "intake-abc")
    assert not intake.owns_case(code, "intake-other") and not intake.owns_case(None, "intake-abc")
    assert not intake.owns_case("ZZZZZZ", "intake-abc")


def test_validated_sessions_outlive_the_upload_window(monkeypatch):
    a = client.post("/intake/start", json={}).json()["case_code"]
    b = client.post("/intake/start", json={}).json()["case_code"]
    intake.SESSIONS[a].update(status="validated", case_id="intake-a")
    for code in (a, b):
        intake.SESSIONS[code]["_created"] -= intake.TTL_S + 60
    with intake._LOCK:
        intake._expire()
    assert a in intake.SESSIONS and b not in intake.SESSIONS


def test_wrong_case_codes_are_locked_out(monkeypatch):
    intake._MISSES.clear()
    intake._ALL_MISSES.clear()
    remote = TestClient(api.app, client=("198.51.100.4", 1))
    for i in range(intake.MISS_LIMIT):
        assert remote.get(f"/intake/ZZZZ{i:02d}").status_code == 404
    assert remote.get("/intake/ZZZZZZ").status_code == 429
    # even a real code is refused while locked; another caller is unaffected
    code = client.post("/intake/start", json={}).json()["case_code"]
    assert remote.get(f"/intake/{code}").status_code == 429
    assert TestClient(api.app, client=("198.51.100.5", 1)).get(f"/intake/{code}").status_code == 200
    intake._MISSES.clear()
    intake._ALL_MISSES.clear()


def test_forged_caller_headers_still_hit_the_global_guess_ceiling(monkeypatch):
    intake._MISSES.clear()
    intake._ALL_MISSES.clear()
    monkeypatch.setattr(intake, "MISS_GLOBAL", 30)
    remote = TestClient(api.app, client=("198.51.100.9", 1))
    for i in range(30):  # a new forged address every request
        assert remote.get(f"/intake/ZZZ{i:03d}", headers={"X-Forwarded-For": f"10.0.{i}.1"}).status_code == 404
    assert remote.get("/intake/ZZZZZZ", headers={"X-Forwarded-For": "10.9.9.9"}).status_code == 429
    intake._MISSES.clear()
    intake._ALL_MISSES.clear()


def test_guess_table_stays_bounded(monkeypatch):
    intake._MISSES.clear()
    monkeypatch.setattr(intake, "MISS_KEYS_MAX", 50)
    remote = TestClient(api.app, client=("198.51.100.10", 1))
    monkeypatch.setattr(intake, "MISS_GLOBAL", 10_000)
    for i in range(200):
        remote.get(f"/intake/ZZ{i:04d}", headers={"X-Forwarded-For": f"10.1.{i // 250}.{i % 250}"})
    assert len(intake._MISSES) <= 50
    intake._MISSES.clear()
    intake._ALL_MISSES.clear()


def test_own_code_on_the_case_list_never_locks_the_victim_out():
    intake._MISSES.clear()
    intake._ALL_MISSES.clear()
    code = client.post("/intake/start", json={}).json()["case_code"]
    intake.SESSIONS[code].update(status="validated", case_id="intake-mine")
    remote = TestClient(api.app, client=("198.51.100.20", 1))
    for _ in range(intake.MISS_LIMIT + 5):
        assert remote.get(f"/cases?code={code}").status_code == 200
    assert remote.get(f"/intake/{code}").status_code == 200
    intake._MISSES.clear()
    intake._ALL_MISSES.clear()


def test_sessions_and_their_cases_survive_a_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("HOUND_STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(intake, "validate_and_build_case", lambda s, ex: {
        "case_id": "intake-restart1", "status": "intake", "source": "screenshot", "chain": "ethereum",
        "sends": [], "victim": s["victim"], "story": s["story"]})
    code = client.post("/intake/start", json={"victim": {"alias": "Ana"}}).json()["case_code"]
    r = client.post(f"/intake/{code}/screenshot", data={"typed": "I sent 100 USDT, tx " + TX})
    assert r.json()["status"] == "validated"
    assert oct((tmp_path / "state.json").stat().st_mode)[-3:] == "600"
    # simulate a restart: memory wiped, then reloaded from the file
    intake.SESSIONS.clear()
    intake._ACTIVE.clear()
    api.CASES.pop("intake-restart1", None)
    api.LIVE_CASES.discard("intake-restart1")
    intake.load_state()
    assert intake.SESSIONS[code]["status"] == "validated" and intake.owns_case(code, "intake-restart1")
    assert "intake-restart1" in api.CASES and "intake-restart1" in api.LIVE_CASES
    assert "intake-restart1" not in api.TRUSTED  # never approved, so never trusted after a restart
    api.CASES.pop("intake-restart1", None)
    api.LIVE_CASES.discard("intake-restart1")


def test_saves_land_in_order_so_a_reset_is_never_undone(monkeypatch, tmp_path):
    import json as _json
    import threading as _th
    monkeypatch.setenv("HOUND_STATE_FILE", str(tmp_path / "state.json"))
    client.post("/intake/start", json={})
    started, release = _th.Event(), _th.Event()
    real_write = intake._write_state

    def slow_write(*a):  # the first save stalls mid-write, holding its (pre-reset) snapshot
        started.set()
        release.wait(5)
        real_write(*a)

    monkeypatch.setattr(intake, "_write_state", slow_write)
    old = _th.Thread(target=intake.save_state)
    old.start()
    started.wait(5)
    monkeypatch.setattr(intake, "_write_state", real_write)
    resetter = _th.Thread(target=intake.reset)  # must wait for the stalled save, then write the empty state
    resetter.start()
    release.set()
    old.join(5)
    resetter.join(5)
    assert _json.loads((tmp_path / "state.json").read_text())["sessions"] == {}
