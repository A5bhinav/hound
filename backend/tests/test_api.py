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

client = TestClient(app, client=("127.0.0.1", 50000))  # localhost: /demo/reset and live cases need it
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
    monkeypatch.setattr(scan, "SUMMARY", tmp_path / "summary_missing.json")  # committed redacted fallback
    monkeypatch.setattr(scan, "weekend_scan", lambda **k: (_ for _ in ()).throw(AssertionError("live scan")))
    r = client.get("/scan/latest")
    assert r.status_code == 200 and r.json()["status"] == "not_computed"


def test_client_posted_case_can_trace_but_never_feeds_the_watchlist(monkeypatch):
    registered = []
    monkeypatch.setattr(api, "register_trace", lambda trace: registered.append(trace["case_id"]) or 0)
    victim_like = {"source": "phone", "sends": [{"chain": "ethereum", "tx_hash": "0x" + "ab" * 32,
                   "from": "0x" + "11" * 20, "to": "0x" + "22" * 20, "token": "USDT", "amount": 5000,
                   "time": "2024-05-01T00:00:00Z"}]}
    cid = client.post("/cases", json=victim_like).json()["case_id"]
    job = client.post(f"/cases/{cid}/trace").json()
    _poll(job["trace_id"])
    assert cid not in registered, "an unverified client case must never mint watchlist holds"
    api.mark_verified(cid)
    job = client.post(f"/cases/{cid}/trace").json()
    _poll(job["trace_id"])
    api.TRUSTED.discard(cid)


# ---- round 2: job deadline, input checks, admin reset, live redaction, packet cache, env, CORS ----

remote = TestClient(app, client=("203.0.113.5", 50000))  # a caller beyond this machine
LIVE_ADDR = "TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE"


def test_job_cap_ordering():
    assert api.ENGINE_BUDGET_S > api.DEFAULTS["deadline_s"]
    assert api.JOB_STALE_S > api.ENGINE_BUDGET_S + api.OTHER_PAYERS_BUDGET_S  # never supersede a live job


def test_engine_overrun_ends_job_as_error_not_running(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(api, "ENGINE_BUDGET_S", 0.3)
    monkeypatch.setattr(api, "run_trace", lambda case, **deps: gate.wait(10))
    try:
        job = client.post(f"/cases/{CASE}/trace").json()
        body = _poll(job["trace_id"], timeout=3)
        assert body["status"] == "error" and "ran over 0.3s" in body["error"]
        assert api.CASES[CASE]["status"] == "intake"
    finally:
        gate.set()


def test_other_payers_overrun_ends_partial(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(api, "OTHER_PAYERS_BUDGET_S", 0.3)
    monkeypatch.setattr(api, "other_payers", lambda trace: gate.wait(10) and [{"address": "late"}])
    try:
        trace = _trace_done()
        assert trace["status"] == "partial" and trace["other_payers"] == []
        assert any("ran over 0.3s" in e["detail"] for e in trace["audit_log"])
    finally:
        gate.set()


def test_other_payers_skipped_when_chain_was_unreachable(monkeypatch):
    real, called = api.run_trace, []

    def with_fetch_errors(case, **deps):
        t = real(case, **deps)
        t["stats"]["fetch_errors"] = 1
        return t

    monkeypatch.setattr(api, "run_trace", with_fetch_errors)
    monkeypatch.setattr(api, "other_payers", lambda trace: called.append(1) or [])
    trace = _trace_done()
    assert called == [] and trace["other_payers"] == []
    assert any(e["step"] == "skip_branch" and "fetch errors" in e["detail"] for e in trace["audit_log"])


def test_engine_value_error_reaches_the_poller(monkeypatch):
    def bad(case, **deps):
        raise ValueError("a case must start on one chain for now, got ['ethereum', 'tron']")

    monkeypatch.setattr(api, "run_trace", bad)
    body = _poll(client.post(f"/cases/{CASE}/trace").json()["trace_id"])
    assert body["status"] == "error" and "one chain" in body["error"]


TRON_SEND = {"chain": "tron", "tx_hash": "a" * 64, "from": LIVE_ADDR, "to": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
             "token": "USDT", "amount": 1, "time": "2026-10-24T00:00:00Z"}


@pytest.mark.parametrize("case, word", [
    ({"sends": [dict(SEND, token="DAI")]}, "token"),
    ({"sends": [SEND, TRON_SEND]}, "one chain"),
    ({"sends": [SEND] * 51}, "limit"),
    ({"sends": [dict(TRON_SEND, to="TXYZ")]}, "Tron address"),
    ({"sends": [dict(TRON_SEND, tx_hash="0x" + "a" * 64)]}, "Tron tx hash"),
    ({"sends": [dict(SEND, time="yesterday")]}, "ISO 8601"),
    ({"sends": [SEND], "created_at": "yesterday"}, "ISO 8601"),
])
def test_post_case_rejects_what_the_engine_would(case, word):
    r = client.post("/cases", json={"source": "phone", **case})
    assert r.status_code == 422 and word in r.json()["detail"]


def test_post_case_uppercases_token_and_accepts_tron():
    c = client.post("/cases", json={"source": "phone", "sends": [dict(SEND, token="usdt")]}).json()
    assert c["sends"][0]["token"] == "USDT"
    assert client.post("/cases", json={"source": "phone", "sends": [TRON_SEND]}).status_code == 200


def test_demo_reset_is_localhost_only_without_token(monkeypatch):
    monkeypatch.delenv("HOUND_ADMIN_TOKEN", raising=False)
    created = client.post("/cases", json={"source": "phone", "sends": [SEND]}).json()["case_id"]
    assert remote.post("/demo/reset").status_code == 403
    assert client.post("/demo/reset", headers={"cf-connecting-ip": "198.51.100.7"}).status_code == 403  # tunnel
    assert client.post("/demo/reset", headers={"x-forwarded-for": "198.51.100.7"}).status_code == 403
    assert created in api.CASES  # nothing was wiped
    # A forwarded request is never local, even one claiming 127.0.0.1 (spoofable through a tunnel).
    # The hidden reset button calls http://localhost:8000/demo/reset directly, or sends X-Hound-Admin.
    assert client.post("/demo/reset", headers={"x-forwarded-for": "127.0.0.1"}).status_code == 403


def test_demo_reset_with_token_needs_the_header(monkeypatch):
    monkeypatch.setenv("HOUND_ADMIN_TOKEN", "s3cret")
    assert client.post("/demo/reset").status_code == 403
    assert remote.post("/demo/reset", headers={"X-Hound-Admin": "wrong"}).status_code == 403
    assert remote.post("/demo/reset", headers={"X-Hound-Admin": "s3cret"}).status_code == 200
    monkeypatch.delenv("HOUND_ADMIN_TOKEN")


def test_cases_live_are_marked_live(monkeypatch, tmp_path):
    live = tmp_path / "data" / "cases_live"
    live.mkdir(parents=True)
    case = {"case_id": "live-1", "created_at": "2026-10-24T00:00:00Z", "source": "phone", "status": "intake",
            "sends": [TRON_SEND]}
    (live / "live-1.case.json").write_text(__import__("json").dumps(case))
    monkeypatch.setattr(api, "ROOT", tmp_path)
    api._load_curated()
    assert "live-1" in api.LIVE_CASES and "live-1" in api.TRUSTED


def _live_case_with_trace():
    cid, tid, jid = "live-x", "t-live-x", "j" * 32
    api.CASES[cid] = {"case_id": cid, "created_at": "2026-10-24T00:00:00Z", "source": "phone", "status": "traced",
                      "victim": {"alias": "Grandma K", "age_band": "70s", "exchange_used": None},
                      "story": {"summary": "met on WhatsApp", "scam_app": None, "platform": None, "first_contact": None},
                      "sends": [TRON_SEND]}
    api.LIVE_CASES.add(cid)
    api.TRACES[tid] = {"trace_id": tid, "case_id": cid, "nodes": [{"address": LIVE_ADDR}],
                       "audit_log": [{"step": "hop", "detail": f"hop to {LIVE_ADDR} via tx {'a' * 64}"}]}
    api.JOBS[jid] = {"case_id": cid, "status": "done", "result_trace_id": tid}
    api.LATEST[cid] = jid
    return cid, jid


def test_live_case_details_never_leave_localhost():
    cid, jid = _live_case_with_trace()
    short = LIVE_ADDR[:6] + "..." + LIVE_ADDR[-4:]
    for path in ("/cases", f"/cases/{cid}/trace", f"/traces/{jid}", "/traces/t-live-x"):
        body = remote.get(path).text
        assert LIVE_ADDR not in body and "a" * 64 not in body and short in body, path
        assert "WhatsApp" not in body and "Grandma" not in body, path
        assert LIVE_ADDR in client.get(path).text, path  # localhost still sees full values
    row = next(r for r in remote.get("/cases").json() if r["case_id"] == cid)
    assert "story" not in row and row["victim"]["alias"] is None and row["victim"]["age_band"] == "70s"
    tunnelled = client.get("/cases", headers={"cf-connecting-ip": "198.51.100.7"}).text
    assert LIVE_ADDR not in tunnelled
    replay = next(r for r in remote.get("/cases").json() if r["case_id"] == CASE)
    assert replay == api.CASES[CASE]  # the public DOJ replay is never redacted


def test_live_packet_redacted_beyond_localhost(monkeypatch):
    cid, _ = _live_case_with_trace()
    api.LAST_DONE[cid] = "t-live-x"
    monkeypatch.setattr(api, "write_case", lambda t, c, a: {"text": f"send to {LIVE_ADDR}", "source": "template"})
    assert LIVE_ADDR not in remote.get(f"/cases/{cid}/packet").text
    assert LIVE_ADDR in client.get(f"/cases/{cid}/packet").text


def test_packet_cached_per_trace_and_audience(monkeypatch):
    _trace_done()
    calls = []

    def fake(trace, case, audience):
        calls.append(audience)
        return {"text": "x", "source": "claude"}

    monkeypatch.setattr(api, "write_case", fake)
    for _ in range(3):
        assert client.get(f"/cases/{CASE}/packet?audience=detective").status_code == 200
    client.get(f"/cases/{CASE}/packet?audience=victim")
    assert calls == ["detective", "victim"]  # repeats never re-call Claude
    assert client.post("/demo/reset").status_code == 200  # reset drops the cache
    _trace_done()
    client.get(f"/cases/{CASE}/packet?audience=detective")
    assert calls == ["detective", "victim", "detective"]


def test_template_packet_not_cached(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _trace_done()
    calls = []
    monkeypatch.setattr(api, "write_case", lambda t, c, a: calls.append(a) or {"text": "x", "source": "template"})
    client.get(f"/cases/{CASE}/packet")
    client.get(f"/cases/{CASE}/packet")
    assert len(calls) == 2  # a Claude failure that fell back to the template may recover next hit


def test_cors_allows_localhost_not_other_origins():
    ok = client.options("/cases", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    evil = client.get("/cases", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers


def test_load_env_never_overrides_and_logs_names_only(monkeypatch, tmp_path, caplog):
    import os
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=from-file-value\nETHERSCAN_API_KEY=eth-file-value\n")
    monkeypatch.delenv("HOUND_NO_DOTENV")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "real-env-value")
    had = "ETHERSCAN_API_KEY" in os.environ
    monkeypatch.delenv("ETHERSCAN_API_KEY", raising=False)
    try:
        with caplog.at_level("INFO", logger="hound.api"):
            api._load_env(env)
        assert os.environ["ANTHROPIC_API_KEY"] == "real-env-value"
        assert os.environ["ETHERSCAN_API_KEY"] == "eth-file-value"
        assert "ANTHROPIC_API_KEY" in caplog.text and "ETHERSCAN_API_KEY" in caplog.text
        assert "value" not in caplog.text
    finally:
        if not had:
            os.environ.pop("ETHERSCAN_API_KEY", None)


def test_load_env_warns_when_anthropic_key_missing(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv("HOUND_NO_DOTENV")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with caplog.at_level("WARNING", logger="hound.api"):
        api._load_env(tmp_path / "missing.env")
    assert "ANTHROPIC_API_KEY unset" in caplog.text


def test_make_demo_fails_loudly_without_anthropic_key():
    from hound.contracts import ROOT
    demo = (ROOT / "Makefile").read_text().split("\ndemo:")[1].split("\n\n")[0]
    assert "ANTHROPIC_API_KEY unset" in demo and "exit 1" in demo


def test_repeat_post_on_running_live_job_is_redacted(monkeypatch):
    cid, _ = _live_case_with_trace()
    api.CASES[cid]["status"] = "traced"
    release = threading.Event()

    def slow(job_id, case, progress):
        progress.append({"step": "hop", "detail": f"hop to {LIVE_ADDR} via tx {'a' * 64}"})
        release.wait(5)
        raise RuntimeError("stop")

    monkeypatch.setattr(api, "_trace_with_fallback", slow)
    try:
        first = remote.post(f"/cases/{cid}/trace")
        assert first.status_code == 200 and LIVE_ADDR not in first.text
        for _ in range(100):
            if api.JOBS[api.LATEST[cid]]["progress"]:
                break
            time.sleep(0.01)
        again = remote.post(f"/cases/{cid}/trace")
        assert again.json()["status"] == "running" and again.json()["audit_log_so_far"]
        assert LIVE_ADDR not in again.text and "a" * 64 not in again.text
        assert LIVE_ADDR in client.post(f"/cases/{cid}/trace").text  # localhost sees full values
    finally:
        release.set()


def test_live_packet_prose_withheld_beyond_localhost(monkeypatch):
    cid, _ = _live_case_with_trace()
    api.LAST_DONE[cid] = "t-live-x"
    monkeypatch.setattr(api, "write_case", lambda t, c, a: {"text": "met on WhatsApp", "cited": ["x"],
                                                          "source": "template", "citations_verified": {}})
    pk = remote.get(f"/cases/{cid}/packet").json()["packet"]
    assert pk["text"] is None and pk["redacted"] is True and pk["cited"] == ["x"]
    assert client.get(f"/cases/{cid}/packet").json()["packet"]["text"] == "met on WhatsApp"


def test_claude_fallback_packet_negative_cached(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    _trace_done()
    calls = []
    monkeypatch.setattr(api, "write_case", lambda t, c, a: calls.append(a) or {"text": "x", "source": "template"})
    for _ in range(3):
        assert client.get(f"/cases/{CASE}/packet").status_code == 200
    assert len(calls) == 1  # Claude failing: no retry inside the TTL
    key = next(iter(api.FALLBACK_PACKETS))
    api.FALLBACK_PACKETS[key] = (api.FALLBACK_PACKETS[key][0], time.monotonic() - 1)
    client.get(f"/cases/{CASE}/packet")
    assert len(calls) == 2  # expired: Claude gets another try


def test_spoofed_forwarded_for_is_never_local():
    from starlette.requests import Request
    def req(headers):
        return Request({"type": "http", "client": ("127.0.0.1", 5000),
                        "headers": [(k.encode(), v.encode()) for k, v in headers.items()]})
    assert api._is_local(req({}))
    assert not api._is_local(req({"x-forwarded-for": "127.0.0.1"}))
    assert not api._is_local(req({"x-forwarded-for": "127.0.0.1, ::1"}))


def test_invalid_curated_case_is_skipped_not_fatal(tmp_path, monkeypatch):
    live = tmp_path / "data" / "cases_live"
    live.mkdir(parents=True)
    (live / "broken.case.json").write_text('{"case_id": "x", "sends": [{"block": 1}]}')
    (tmp_path / "data" / "cases").mkdir()
    (tmp_path / "examples").mkdir()
    import shutil
    from hound.contracts import ROOT
    shutil.copy(ROOT / "examples" / "ohnd_replay.case.json", tmp_path / "examples" / "ohnd_replay.case.json")
    monkeypatch.setattr(api, "ROOT", tmp_path)
    api._load_curated()
    assert any(s["file"] == "broken.case.json" for s in api.SKIPPED_CASES)
    assert "broken.case.json" in client.get("/health").json()["skipped_cases"]
    monkeypatch.undo()
    api._load_curated()


def test_intake_router_is_included_when_present(monkeypatch):
    import types as _types
    from fastapi import APIRouter, FastAPI
    r = APIRouter()
    r.add_api_route("/intake/active", lambda: {"ok": True}, methods=["GET"])
    monkeypatch.setitem(sys.modules, "hound.intake.routes", _types.SimpleNamespace(router=r))
    target = FastAPI()
    api._include_intake_router(target)
    assert "/intake/active" in api._route_paths(target.routes)


# ---- round 3: prewarm after reset, packet cache eviction, writer crash ----

def test_prewarm_retraces_replay_and_writes_both_packets(monkeypatch):
    calls = []
    monkeypatch.setattr(api, "write_case", lambda t, c, a: calls.append(a) or {"text": "x", "source": "claude"})
    assert CASE == api.REPLAY_CASE
    api._prewarm(api._GENERATION)
    tid = api.LAST_DONE[CASE]
    assert tid in api.TRACES and calls == ["victim", "detective"]
    assert {(tid, "victim"), (tid, "detective")} <= set(api.PACKETS)
    assert client.get(f"/cases/{CASE}/packet?audience=victim").status_code == 200 and len(calls) == 2  # served warm


def test_prewarm_drops_results_after_another_reset(monkeypatch):
    def reset_mid_write(t, c, a):
        api._GENERATION += 1  # a /demo/reset landed while the packet was being written
        return {"text": "x", "source": "claude"}

    monkeypatch.setattr(api, "write_case", reset_mid_write)
    api._prewarm(api._GENERATION)
    assert not api.PACKETS


def test_prewarm_for_an_old_generation_never_writes():
    api._prewarm(api._GENERATION - 1)
    assert CASE not in api.LAST_DONE and not api.PACKETS


def test_reset_starts_prewarm_in_background(monkeypatch):
    started = []
    monkeypatch.delenv("HOUND_NO_PREWARM")
    monkeypatch.setattr(api, "_prewarm", lambda g: started.append(g))
    assert client.post("/demo/reset").status_code == 200
    for _ in range(100):
        if started:
            break
        time.sleep(0.01)
    assert started == [api._GENERATION]


def test_retrace_evicts_stale_packet(monkeypatch):
    first = _trace_done()
    api.PACKETS[(first["trace_id"], "detective")] = {"text": "stale", "source": "claude"}
    api.FALLBACK_PACKETS[(first["trace_id"], "victim")] = ({"text": "stale"}, time.monotonic() + 60)
    second = _trace_done()
    assert (second["trace_id"], "detective") not in api.PACKETS
    assert (second["trace_id"], "victim") not in api.FALLBACK_PACKETS


def test_writer_assertion_is_a_plain_500(monkeypatch, caplog):
    _trace_done()
    monkeypatch.setattr(api, "write_case", lambda t, c, a: (_ for _ in ()).throw(AssertionError("cite mismatch")))
    with caplog.at_level("ERROR", logger="hound.api"):
        r = TestClient(app, raise_server_exceptions=False, client=("127.0.0.1", 50000)).get(f"/cases/{CASE}/packet")
    assert r.status_code == 500 and "could not be written" in r.json()["detail"]
    assert "cite mismatch" in caplog.text
