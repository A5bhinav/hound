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
    assert cid in api.CASES and cid in api.TRUSTED
    assert api.CASES[cid]["sends"][0]["amount"] == 11082.48 and api.CASES[cid]["source"] == "screenshot"
    assert client.get("/intake/active").json()["status"] == "validated"


def test_amount_mismatch_asks_for_retake(monkeypatch):
    import hound.chain as chain
    monkeypatch.setattr(chain, "tx_sends", _fake_tx_sends)
    code = client.post("/intake/start", json={}).json()["case_code"]
    r = client.post(f"/intake/{code}/screenshot", data={"typed": f"sent 500 USDT hash {TX}"})
    assert r.json()["status"] == "needs_retake" and "amount" in r.json()["message"]
    assert f"intake-{code.lower()}" not in api.TRUSTED


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


def test_extract_from_text_handles_truncated_address_and_amount():
    ex = intake.extract_from_text("Sent 96,028.85 USDT to 0x2f1c…8fa4 on 2026-10-08 15:45")
    assert ex["amount"] == 96028.85 and ex["token"] == "USDT" and ex["to_prefix"] == "0x2f1c" and ex["to_suffix"] == "8fa4" and ex["time"].startswith("2026-10-08")
