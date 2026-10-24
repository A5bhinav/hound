import sys
import threading
import time
import types

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

import hound.api as api
from hound import fixture_chain
from hound.api import app
from hound.contracts import example

client = TestClient(app)
A7 = "0xa1770ead287dc8e91631a7a323390d5b744f0021"
CASE = example("ohnd_replay.case")["case_id"]  # ETH-send case: A.H.'s six real ETH sends
SEND = {"chain": "ethereum", "tx_hash": "0x1", "from": "0xa", "to": "0xb", "token": "USDT", "amount": 1,
        "time": "2026-10-24T00:00:00Z"}


@pytest.fixture(autouse=True)
def _reset():
    assert client.post("/demo/reset").status_code == 200
    yield
    client.post("/demo/reset")


def _poll(job_id, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/traces/{job_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError(f"trace job {job_id} still running after {timeout}s")


def _trace_done():
    job = client.post(f"/cases/{CASE}/trace").json()
    trace = _poll(job["trace_id"])
    assert trace["status"] in ("done", "partial"), trace
    return trace


def test_end_to_end_async():
    cases = client.get("/cases").json()
    assert any(c["case_id"] == CASE for c in cases)
    started = client.post(f"/cases/{CASE}/trace").json()
    assert started["case_id"] == CASE and started["status"] == "running"
    assert len(started["trace_id"]) == 32
    trace = _poll(started["trace_id"])
    assert trace["status"] in ("done", "partial")
    assert {e["address"] for e in trace["endpoints"]} >= {A7}
    assert client.get(f"/traces/{trace['trace_id']}").json()["trace_id"] == trace["trace_id"]
    assert client.get(f"/cases/{CASE}/trace").json()["trace_id"] == trace["trace_id"]
    assert api.CASES[CASE]["status"] == "traced"
    packet = client.get(f"/cases/{CASE}/packet?audience=detective").json()
    assert A7 in packet["packet"]["text"]
    assert client.get(f"/check?chain=ethereum&address={A7}").json()["decision"] == "hold"


def test_eth_send_case_does_not_error():
    case = api.CASES[CASE]
    assert any(s["token"] == "ETH" for s in case["sends"])
    trace = _trace_done()
    assert trace["status"] != "error"


def test_chain_deps_forwards_native_txs_from_real_chain(monkeypatch):
    full = types.SimpleNamespace(**{k: getattr(fixture_chain, k) for k in api.CHAIN_FUNCS},
                                 get_native_txs=lambda *a, **k: [])
    monkeypatch.setitem(sys.modules, "hound.chain", full)
    deps, using_fixture = api._chain_deps(api.CASES[CASE])
    assert not using_fixture
    assert deps["get_native_txs"] is full.get_native_txs
    assert deps["get_transfers"] is full.get_transfers


def test_chain_deps_without_native_txs_uses_fixture_for_eth_case(monkeypatch, caplog):
    real = types.SimpleNamespace(**{k: (lambda *a, **k: None) for k in api.CHAIN_FUNCS})
    monkeypatch.setitem(sys.modules, "hound.chain", real)
    with caplog.at_level("WARNING", logger="hound.api"):
        deps, using_fixture = api._chain_deps(api.CASES[CASE])
    assert using_fixture
    assert deps["get_native_txs"] is fixture_chain.get_native_txs
    assert deps["get_transfers"] is fixture_chain.get_transfers
    assert "get_native_txs" in caplog.text
    usdt, using_fixture = api._chain_deps({"sends": [SEND]})
    assert not using_fixture
    assert usdt["get_transfers"] is real.get_transfers and usdt["get_native_txs"] is None


def test_fixture_fallback_when_chain_missing(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "hound.chain", types.SimpleNamespace())
    with caplog.at_level("WARNING", logger="hound.api"):
        deps, using_fixture = api._chain_deps({"sends": [SEND]})
    assert using_fixture
    assert deps["get_transfers"] is fixture_chain.get_transfers
    assert deps["get_native_txs"] is fixture_chain.get_native_txs
    assert "REAL CHAIN ADAPTERS MISSING" in caplog.text


def test_running_state_then_done(monkeypatch):
    gate = threading.Event()
    real = api.run_trace

    def slow(case, **deps):
        assert gate.wait(10), "test gate never opened"
        return real(case, **deps)

    monkeypatch.setattr(api, "run_trace", slow)
    job = client.post(f"/cases/{CASE}/trace").json()
    assert job["status"] == "running"
    view = client.get(f"/traces/{job['trace_id']}").json()
    assert {k: view[k] for k in ("trace_id", "case_id", "status")} == {"trace_id": job["trace_id"], "case_id": CASE, "status": "running"}
    assert view["started_at"].endswith("Z") and view["elapsed_s"] >= 0
    assert client.get(f"/cases/{CASE}/trace").json()["status"] == "running"
    assert client.post(f"/cases/{CASE}/trace").json()["trace_id"] == job["trace_id"]  # no duplicate job
    assert client.get(f"/cases/{CASE}/packet").status_code == 409
    gate.set()
    assert _poll(job["trace_id"])["status"] in ("done", "partial")


def test_engine_error_is_redacted(monkeypatch, caplog):
    def boom(case, **deps):
        raise RuntimeError("GET https://api.etherscan.io/v2/api?module=account&apikey=SECRET failed")

    monkeypatch.setattr(api, "run_trace", boom)
    with caplog.at_level("ERROR", logger="hound.api"):
        job = client.post(f"/cases/{CASE}/trace").json()
        body = _poll(job["trace_id"])
    assert body["status"] == "error"
    assert body["error"].startswith("RuntimeError: ")
    assert "SECRET" not in body["error"] and "etherscan" not in body["error"]
    assert "SECRET" not in client.get(f"/cases/{CASE}/trace").text
    assert "apikey=REDACTED" in caplog.text and "SECRET" not in caplog.text
    assert client.get(f"/cases/{CASE}/packet").status_code == 409
    assert api.CASES[CASE]["status"] == "intake"


def test_retrace_never_goes_backwards(monkeypatch):
    first = _trace_done()
    gate = threading.Event()

    def fail(case, **deps):
        assert gate.wait(10)
        raise ValueError("second run fails")

    monkeypatch.setattr(api, "run_trace", fail)
    job = client.post(f"/cases/{CASE}/trace").json()
    # while the re-trace runs, the packet still serves the last good trace
    assert client.get(f"/cases/{CASE}/packet").json()["trace"]["trace_id"] == first["trace_id"]
    gate.set()
    assert _poll(job["trace_id"])["status"] == "error"
    assert api.CASES[CASE]["status"] == "traced"  # restored, not reset to intake
    assert client.get(f"/cases/{CASE}/packet").json()["trace"]["trace_id"] == first["trace_id"]


def test_hung_job_is_replaced_after_deadline(monkeypatch):
    gate = threading.Event()
    real = api.run_trace

    def hang(case, **deps):
        gate.wait(10)
        return real(case, **deps)

    monkeypatch.setattr(api, "run_trace", hang)
    hung = client.post(f"/cases/{CASE}/trace").json()
    api.JOBS[hung["trace_id"]]["started_mono"] -= api.JOB_STALE_S + 1
    monkeypatch.setattr(api, "run_trace", real)
    fresh = client.post(f"/cases/{CASE}/trace").json()
    assert fresh["trace_id"] != hung["trace_id"]
    assert _poll(fresh["trace_id"])["status"] in ("done", "partial")
    old = client.get(f"/traces/{hung['trace_id']}").json()
    assert old["status"] == "error" and "superseded" in old["error"]
    gate.set()  # the hung thread finishing late must not overwrite the newer result
    time.sleep(0.5)
    assert client.get(f"/traces/{hung['trace_id']}").json()["status"] == "error"
    assert client.get(f"/cases/{CASE}/trace").json()["trace_id"] == client.get(f"/cases/{CASE}/packet").json()["trace"]["trace_id"]


def test_demo_reset_clears_state():
    created = client.post("/cases", json={"source": "phone", "sends": [SEND]}).json()
    job = client.post(f"/cases/{CASE}/trace").json()
    _poll(job["trace_id"])
    r = client.post("/demo/reset").json()
    assert r["ok"] and r["cases"] >= 1
    ids = {c["case_id"] for c in client.get("/cases").json()}
    assert CASE in ids and created["case_id"] not in ids
    assert client.get(f"/traces/{job['trace_id']}").status_code == 404
    assert client.get(f"/cases/{CASE}/trace").status_code == 404
    assert client.get(f"/cases/{CASE}/packet").status_code == 409
    assert client.get("/health").json()["traces"] == 0


@pytest.mark.parametrize("chain,address", [
    ("ethereum", "0x123"),
    ("ethereum", "a1770ead287dc8e91631a7a323390d5b744f0021"),
    ("ethereum", "0xg1770ead287dc8e91631a7a323390d5b744f0021"),
    ("tron", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6"),
    ("tron", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj60"),  # 0 is not base58
    ("solana", A7),
])
def test_mounted_check_rejects_malformed_address(chain, address):
    r = client.get(f"/check?chain={chain}&address={address}")
    assert 400 <= r.status_code < 500, r.text


def test_mounted_check_is_the_watch_router_and_normalises():
    # Jinka's router serves /check, so the fallback route must not have been added
    assert "/check" in api._route_paths(app.routes)
    assert not [r for r in app.routes if getattr(r, "endpoint", None) is api.check_address]
    assert client.get(f"/check?chain=ethereum&address={A7.upper().replace('0X', '0x')}").json()["decision"] == "hold"
    assert client.get("/check?chain=tron&address=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t").status_code == 200


@pytest.mark.parametrize("chain,address,code", [
    ("ethereum", "0x123", 400), ("tron", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj60", 400), ("solana", A7, 422),
])
def test_fallback_check_validates(monkeypatch, chain, address, code):
    monkeypatch.setitem(sys.modules, "hound.watch.routes", types.SimpleNamespace(router=APIRouter()))
    fresh = FastAPI()
    api._include_watch_router(fresh)
    assert TestClient(fresh).get(f"/check?chain={chain}&address={address}").status_code == code


def test_router_check_wins_over_fallback(monkeypatch):
    router = APIRouter()
    router.add_api_route("/check", lambda: {"from": "watch.routes"}, methods=["GET"])
    monkeypatch.setitem(sys.modules, "hound.watch.routes", types.SimpleNamespace(router=router))
    fresh = FastAPI()
    api._include_watch_router(fresh)
    assert TestClient(fresh).get(f"/check?chain=ethereum&address={A7}").json() == {"from": "watch.routes"}
    assert not [r for r in fresh.routes if getattr(r, "endpoint", None) is api.check_address]  # no fallback


def test_packet_before_trace_is_409():
    r = client.post("/cases", json={"source": "phone", "sends": [SEND]})
    assert r.status_code == 200
    assert client.get(f"/cases/{r.json()['case_id']}/packet").status_code == 409


def test_unknown_ids_are_404():
    assert client.get("/traces/nope").status_code == 404
    assert client.get("/cases/nope/trace").status_code == 404
    assert client.post("/cases/nope/trace").status_code == 404


def test_invalid_case_is_422():
    assert client.post("/cases", json={"source": "fax", "sends": []}).status_code == 422


def test_watch_routes_without_router_fails_loudly(monkeypatch):
    monkeypatch.setitem(sys.modules, "hound.watch.routes", types.SimpleNamespace())
    with pytest.raises(RuntimeError, match="APIRouter"):
        api._include_watch_router(FastAPI())


def test_make_demo_prefers_cache():
    from hound.contracts import ROOT
    demo = (ROOT / "Makefile").read_text().split("\ndemo:")[1].split("\n\n")[0]
    assert "HOUND_CACHE_MODE=prefer_cache" in demo  # AUDIT N5: judges may try their own scenario
    assert "HOUND_OFFLINE=1" not in demo and "readonly" not in demo


def test_audit_log_streams_while_running(monkeypatch):
    """A chain call blocks mid-trace; the poll must already show the audit entries written so far."""
    import hound.chain as chain
    entered, gate = threading.Event(), threading.Event()
    calls = {"n": 0}
    real = chain.get_transfers

    def blocking(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:  # block partway: after the first fetch has been audited
            entered.set()
            assert gate.wait(10), "test gate never opened"
        return real(*a, **k)

    monkeypatch.setattr(chain, "get_transfers", blocking)
    job = client.post(f"/cases/{CASE}/trace").json()
    try:
        assert entered.wait(10), "trace never reached the second get_transfers call"
        view = client.get(f"/traces/{job['trace_id']}").json()
        assert view["status"] == "running"
        assert len(view["audit_log_so_far"]) > 0
    finally:
        gate.set()
    done = _poll(job["trace_id"])
    assert done["status"] in ("done", "partial")
    assert done["job_id"] == job["trace_id"]


def test_other_payers_failure_keeps_trace(monkeypatch, caplog):
    def boom(trace):
        raise RuntimeError("GET https://eth.blockscout.com/api?apikey=SECRET timed out")

    monkeypatch.setattr(api, "other_payers", boom)
    with caplog.at_level("ERROR", logger="hound.api"):
        trace = _trace_done()
    assert trace["other_payers"] == []
    assert "other_payers failed" in caplog.text and "SECRET" not in caplog.text
    assert client.get(f"/cases/{CASE}/packet").status_code == 200


def test_other_payers_skipped_on_fixture_fallback(monkeypatch):
    called = []
    monkeypatch.setattr(api, "_chain_deps", lambda case: ({k: getattr(fixture_chain, k) for k in api.CHAIN_FUNCS + ("get_native_txs",)}, True))
    monkeypatch.setattr(api, "other_payers", lambda trace: called.append(1) or [{"address": "live"}])
    trace = _trace_done()
    assert called == [] and trace["other_payers"] == []


def test_done_response_carries_job_id():
    job = client.post(f"/cases/{CASE}/trace").json()
    done = _poll(job["trace_id"])
    assert done["job_id"] == job["trace_id"]
    assert client.get(f"/cases/{CASE}/trace").json()["job_id"] == job["trace_id"]
