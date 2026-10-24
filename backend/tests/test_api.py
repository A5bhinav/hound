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
SEND = {"chain": "ethereum", "tx_hash": "0x" + "1" * 64, "from": "0x" + "a" * 40, "to": "0x" + "b" * 40,
        "token": "USDT", "amount": 1, "time": "2026-10-24T00:00:00Z"}


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
    deps = api._chain_deps(api.CASES[CASE])
    assert deps["get_native_txs"] is full.get_native_txs
    assert deps["get_transfers"] is full.get_transfers


def test_chain_deps_without_native_txs_raises_only_for_eth_case(monkeypatch):
    real = types.SimpleNamespace(**{k: (lambda *a, **k: None) for k in api.CHAIN_FUNCS})
    monkeypatch.setitem(sys.modules, "hound.chain", real)
    with pytest.raises(api.MissingAdapters, match="get_native_txs"):
        api._chain_deps(api.CASES[CASE])
    usdt = api._chain_deps({"sends": [SEND]})
    assert usdt["get_transfers"] is real.get_transfers and usdt["get_native_txs"] is None


def test_fixture_fallback_only_for_replay_and_marked(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "hound.chain", types.SimpleNamespace())
    with caplog.at_level("WARNING", logger="hound.api"):
        trace = _trace_done()
    assert trace["source"] == "fixture" and trace["other_payers"] == []
    assert {e["address"] for e in trace["endpoints"]} >= {A7}
    assert "REAL CHAIN ADAPTERS MISSING" in caplog.text


def test_missing_adapters_on_live_case_is_error_not_fixture(monkeypatch):
    monkeypatch.setitem(sys.modules, "hound.chain", types.SimpleNamespace())
    cid = client.post("/cases", json={"source": "phone", "sends": [SEND]}).json()["case_id"]
    body = _poll(client.post(f"/cases/{cid}/trace").json()["trace_id"])
    assert body["status"] == "error" and body["error"].startswith("MissingAdapters:")
    assert not api.TRACES


@pytest.mark.parametrize("make_err", [
    lambda: __import__("hound.chain.net", fromlist=["x"]).ChainAPIError("GET https://x/api?apikey=SECRET 503"),
    lambda: __import__("hound.chain.cache", fromlist=["x"]).CacheMiss("nothing cached apikey=SECRET"),
    lambda: RuntimeError("call budget or deadline exhausted while resolving ETH swaps token=SECRET"),
])
def test_chain_error_never_falls_back_to_fixture(monkeypatch, make_err):
    calls = []

    def boom(case, **kw):
        calls.append(kw["get_transfers"])
        raise make_err()

    monkeypatch.setattr(api, "run_trace", boom)
    body = _poll(client.post(f"/cases/{CASE}/trace").json()["trace_id"])
    assert body["status"] == "error" and "SECRET" not in body["error"]
    assert body["error"].startswith(type(make_err()).__name__ + ":")
    assert len(calls) == 1  # one attempt on the real adapters, no fixture retry
    assert not api.TRACES and api.CASES[CASE]["status"] != "traced"


def test_engine_adapters_missing_type_triggers_fallback(monkeypatch):
    engine_type = getattr(api.trace_module, "AdaptersMissing", None)
    if engine_type is not None:
        assert engine_type in api.FALLBACK_ERRORS
    fake = type("AdaptersMissing", (RuntimeError,), {})
    monkeypatch.setattr(api, "FALLBACK_ERRORS", (api.MissingAdapters, fake))
    real_run = api.run_trace
    seen = []

    def first_fails(case, **kw):
        seen.append(kw["get_transfers"])
        if len(seen) == 1:
            raise fake("case has ETH sends but no get_native_txs adapter")
        return real_run(case, **kw)

    monkeypatch.setattr(api, "run_trace", first_fails)
    trace = _trace_done()
    assert trace["source"] == "fixture" and seen[1] is fixture_chain.get_transfers


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
    monkeypatch.setitem(sys.modules, "hound.chain", types.SimpleNamespace())
    monkeypatch.setattr(api, "other_payers", lambda trace: called.append(1) or [{"address": "live"}])
    trace = _trace_done()
    assert called == [] and trace["other_payers"] == []


def test_done_response_carries_job_id():
    job = client.post(f"/cases/{CASE}/trace").json()
    done = _poll(job["trace_id"])
    assert done["job_id"] == job["trace_id"]
    assert client.get(f"/cases/{CASE}/trace").json()["job_id"] == job["trace_id"]


def test_unusable_trace_or_audience_is_422_not_500():
    r = client.post("/cases", json={"source": "phone", "sends": [SEND]})
    cid = r.json()["case_id"]
    api.TRACES[f"t-{cid}"] = {"trace_id": f"t-{cid}", "case_id": cid, "nodes": [], "edges": [], "endpoints": []}
    api.LAST_DONE[cid] = f"t-{cid}"
    try:
        r = client.get(f"/cases/{cid}/packet")
        assert r.status_code == 422 and "no endpoints" in r.json()["detail"]
    finally:
        api.TRACES.pop(f"t-{cid}")
        api.LAST_DONE.pop(cid, None)
    _trace_done()
    assert client.get(f"/cases/{CASE}/packet?audience=press").status_code == 422


def test_list_cases_returns_full_validated_cases():
    from hound.contracts import validate_case
    rows = client.get("/cases").json()
    assert rows and all(validate_case(r) and r["sends"] for r in rows)
    assert next(r for r in rows if r["case_id"] == CASE) == api.CASES[CASE]


@pytest.mark.parametrize("extra", [{"case_id": CASE}, {"source": "doj_replay"}, {"freeze_visibility": "hidden"},
                                   {"data_cutoff_block": 1}])
def test_post_case_rejects_server_owned_fields(extra):
    before = dict(api.CASES[CASE])
    r = client.post("/cases", json={"source": "phone", "sends": [SEND], **extra})
    assert r.status_code == 400
    assert api.CASES[CASE] == before


def test_post_case_lowercases_eth_hex_and_rejects_malformed():
    upper = dict(SEND, tx_hash="0x" + "AB" * 32, to="0x" + "CD" * 20, **{"from": "0x" + "EF" * 20})
    c = client.post("/cases", json={"source": "phone", "sends": [upper]}).json()
    s = c["sends"][0]
    assert (s["tx_hash"], s["to"], s["from"]) == ("0x" + "ab" * 32, "0x" + "cd" * 20, "0x" + "ef" * 20)
    assert api.CASES[c["case_id"]]["sends"][0]["to"] == "0x" + "cd" * 20
    assert client.post("/cases", json={"source": "phone", "sends": [dict(SEND, to="0xb")]}).status_code == 400
    assert client.post("/cases", json={"source": "phone", "sends": [dict(SEND, tx_hash="0x1")]}).status_code == 400


def test_trace_registers_with_watchlist(monkeypatch, tmp_path):
    from hound.watch import watchlist
    monkeypatch.setenv("HOUND_TRACE_DIRS", str(tmp_path))  # nothing preloaded: only the live trace counts
    watchlist.reset()
    addrs = {n["address"] for n in example("ohnd_replay.trace")["nodes"]}
    before = {a for a in addrs if client.get(f"/check?chain=ethereum&address={a}").json()["decision"] == "hold"}
    _trace_done()
    after = {a for a in addrs if client.get(f"/check?chain=ethereum&address={a}").json()["decision"] == "hold"}
    assert after - before, "no unfrozen wallet from the new trace is held"


def test_register_failure_keeps_trace(monkeypatch, caplog):
    monkeypatch.setattr(api, "register_trace", lambda t: 1 / 0)
    with caplog.at_level("ERROR", logger="hound.api"):
        trace = _trace_done()
    assert "register_trace failed" in caplog.text and api.TRACES[trace["trace_id"]]


def test_scoreboard_scores_latest_replay_trace():
    assert client.get("/proof/scoreboard").json()["summary"]["status"] == "no_trace"
    trace = _trace_done()
    board = client.get("/proof/scoreboard").json()
    assert board["summary"]["status"] != "no_trace" and board["trace_source"] == trace["source"]
    assert board["summary"]["intermediates_reached"] > 0


def test_scan_route_never_scans_live(monkeypatch, tmp_path):
    from hound.proof import scan
    monkeypatch.setattr(scan, "OUT", tmp_path / "scan_missing.json")
    monkeypatch.setattr(scan, "weekend_scan", lambda **k: (_ for _ in ()).throw(AssertionError("live scan")))
    r = client.get("/scan/latest")
    assert r.status_code == 200 and r.json()["status"] == "not_computed"
