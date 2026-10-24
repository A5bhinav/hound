from fastapi.testclient import TestClient

from hound.api import app

client = TestClient(app)
A7 = "0xa1770ead287dc8e91631a7a323390d5b744f0021"


def test_end_to_end_on_stubs():
    cases = client.get("/cases").json()
    assert any(c["case_id"] == "ohnd-replay-001" for c in cases)
    trace = client.post("/cases/ohnd-replay-001/trace").json()
    assert {e["address"] for e in trace["endpoints"]} >= {A7}
    assert client.get(f"/traces/{trace['trace_id']}").status_code == 200
    packet = client.get("/cases/ohnd-replay-001/packet?audience=detective").json()
    assert A7 in packet["packet"]["text"]
    assert client.get(f"/check?chain=ethereum&address={A7}").json()["decision"] == "hold"


def test_packet_before_trace_is_409():
    r = client.post("/cases", json={"source": "phone", "sends": [{"chain": "ethereum", "tx_hash": "0x1", "from": "0xa", "to": "0xb", "token": "USDT", "amount": 1, "time": "2026-10-24T00:00:00Z"}]})
    assert r.status_code == 200
    assert client.get(f"/cases/{r.json()['case_id']}/packet").status_code == 409


def test_invalid_case_is_422():
    assert client.post("/cases", json={"source": "fax", "sends": []}).status_code == 422
