"""Offline tests for watch/: watchlist rules, check() decisions, other payers. Chain calls are faked."""

import json
from pathlib import Path

import pytest

from hound import chain
import importlib
check_mod = importlib.import_module("hound.watch.check")
op_mod = importlib.import_module("hound.watch.other_payers")
from hound.watch.watchlist import Watchlist

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "mini.trace.json").read_text())
VICTIM = "0x1111111111111111111111111111111111111111"
A1 = "0xcf9bbfa762ef5a84ba3d25350de941a6db485027"
HOP2 = "0x78366b2f6c5321ac30629c078120385ae2da1a06"
HOP3 = "0x9eb0c71e79066552bdd05a69fc4dcac075db5e1f"
A7 = "0xa1770ead287dc8e91631a7a323390d5b744f0021"
BINANCE14 = "0x28c6c06298d514db089934071355e5743bf21d60"
OFAC_ADDR = "0x7f367cc41522ce07553e823bf3be79a889debe1b"  # on the OFAC SDN list


@pytest.fixture
def not_frozen(monkeypatch):
    monkeypatch.setattr(chain, "freeze_status",
                        lambda c, a, **k: {"is_frozen": False, "frozen_at": None, "freeze_tx": None})


@pytest.fixture
def wl():
    w = Watchlist()
    w.add_trace(FIXTURE)
    return w


def test_watchlist_never_lists_victims_or_exchanges(wl):
    assert wl.lookup("ethereum", VICTIM) is None
    assert wl.lookup("ethereum", BINANCE14) is None
    assert wl.lookup("ethereum", A1)["direct_hit"] is True
    assert wl.lookup("ethereum", HOP2)["direct_hit"] is False


def test_traced_node_high_confidence_holds(wl, not_frozen):
    r = check_mod.check("ethereum", A1, watch=wl)
    assert r["decision"] == "hold"
    assert r["evidence"]["case_ids"] == ["fixture-case-1"]
    assert check_mod.check("ethereum", HOP2, watch=wl)["decision"] == "hold"  # conf 0.9, 1000 USDT


def test_mid_confidence_is_warn_not_hold(wl, not_frozen):
    # HOP3's only inbound edge has confidence 0.55
    r = check_mod.check("ethereum", HOP3, watch=wl)
    assert r["decision"] == "warn"
    assert any("never a hold" in x for x in r["reasons"])


def test_reports_alone_never_hold(wl, not_frozen):
    addr = "0x4444444444444444444444444444444444444444"
    wl.add_reports([{"address": addr, "chain": "ethereum", "report_count": 25, "confidence": 0.99}])
    r = check_mod.check("ethereum", addr, watch=wl)
    assert r["decision"] == "warn"
    assert any("reports alone never hold" in x for x in r["reasons"])


def test_reports_do_not_lift_low_confidence_to_hold(wl, not_frozen):
    wl.add_reports([{"address": HOP3, "chain": "ethereum", "report_count": 3, "confidence": 0.5}])
    assert check_mod.check("ethereum", HOP3, watch=wl)["decision"] == "warn"


def test_invalid_address_is_value_error(wl):
    with pytest.raises(ValueError):
        check_mod.check("ethereum", "0x123", watch=wl)


def test_exchange_is_allowed_even_if_reported(wl, not_frozen):
    wl.add_reports([{"address": BINANCE14, "chain": "ethereum", "report_count": 50}])
    r = check_mod.check("ethereum", BINANCE14, watch=wl)
    assert r["decision"] == "allow"
    assert wl.lookup("ethereum", BINANCE14) is None


def test_ofac_holds(wl, not_frozen):
    assert check_mod.check("ethereum", OFAC_ADDR, watch=wl)["decision"] == "hold"


def test_frozen_holds(wl, monkeypatch):
    monkeypatch.setattr(chain, "freeze_status", lambda c, a, **k: {"is_frozen": True, "frozen_at": "2024-06-21T14:53:11Z",
                                                              "freeze_tx": "0x5b12"})
    r = check_mod.check("ethereum", A7, watch=wl)
    assert r["decision"] == "hold"
    assert r["evidence"]["frozen"]["freeze_tx"] == "0x5b12"


def test_unknown_allowed(wl, not_frozen):
    r = check_mod.check("ethereum", "0x2222222222222222222222222222222222222222", watch=wl)
    assert r["decision"] == "allow"


def test_freeze_api_down_still_answers(wl, monkeypatch):
    def boom(c, a, **k):
        raise chain.ChainAPIError("rpc down")
    monkeypatch.setattr(chain, "freeze_status", boom)
    r = check_mod.check("ethereum", A1, watch=wl)
    assert r["decision"] == "hold"
    assert "freeze_check_error" in r["evidence"]


# ------------------------------------------------------------------ other payers

PAYER = "0x3333333333333333333333333333333333333333"
PASS_THROUGH = "0x5555555555555555555555555555555555555555"
HER_EXCHANGE = "0x6666666666666666666666666666666666666666"  # the victim's own wallet upstream
COINBASE10 = "0xa9d1e08c7793af67e9d92fe308d5697fb81d3e43"


def test_other_payers_count_payments_into_the_entry_layer(monkeypatch):
    """Entry layer = the scam wallet the victim paid (A1) + outside senders into the next layer
    (HOP2). Payments into the victim's own wallet, and her own upstream paying the scam, never count."""
    def fake_transfers(ch, address, token="USDT", as_of=None, after=None):
        if token != "USDT":
            return []
        if address == VICTIM:  # her own exchange account funding her wallet: not another payer
            return [{"from": HER_EXCHANGE, "to": VICTIM, "amount": 9000.0, "time": "2024-05-01T00:00:00Z",
                     "tx_hash": "0xself", "token": "USDT"}]
        if address == A1:  # the entry wallet the victim paid
            return [{"from": COINBASE10, "to": A1, "amount": 300.0, "time": "2024-05-02T00:00:00Z",
                     "tx_hash": "0xc1", "token": "USDT"},
                    {"from": COINBASE10, "to": A1, "amount": 500.0, "time": "2024-05-03T00:00:00Z",
                     "tx_hash": "0xc2", "token": "USDT"},
                    {"from": PAYER, "to": A1, "amount": 50.0, "time": "2024-05-03T00:00:00Z",
                     "tx_hash": "0xdust", "token": "USDT"},
                    {"from": HER_EXCHANGE, "to": A1, "amount": 700.0, "time": "2024-05-03T00:00:00Z",
                     "tx_hash": "0xherself", "token": "USDT"}]
        if address == HOP2:  # next layer: an outside pass-through sends in
            return [{"from": PASS_THROUGH, "to": HOP2, "amount": 4000.0, "time": "2024-05-02T00:00:00Z",
                     "tx_hash": "0xs1", "token": "USDT"}]
        if address == PASS_THROUGH:
            return [{"from": COINBASE10, "to": PASS_THROUGH, "amount": 4100.0, "time": "2024-05-01T12:00:00Z",
                     "tx_hash": "0xc3", "token": "USDT"},
                    {"from": HOP3, "to": PASS_THROUGH, "amount": 900.0, "time": "2024-05-01T12:00:00Z",
                     "tx_hash": "0xinternal", "token": "USDT"}]
        return []

    monkeypatch.setattr(chain, "get_transfers", fake_transfers)
    monkeypatch.setattr(chain, "get_native_txs", lambda *a, **k: [], raising=False)
    rows = op_mod.payments(FIXTURE, window_days=7)
    # dust, trace-internal, the victim's own wallet and her own upstream are all excluded
    assert [r["tx_hash"] for r in rows] == ["0xc3", "0xc1", "0xc2"]
    assert {r["entry_address"] for r in rows} == {A1, PASS_THROUGH}
    assert VICTIM not in {r["entry_address"] for r in rows}
    assert all(r["source_exchange"] == "Coinbase" for r in rows)
    assert op_mod.summary(rows)["text"] == "3 payments in from 1 exchange into 2 entry addresses"
    schema_rows = op_mod.other_payers(FIXTURE, window_days=7)
    assert len(schema_rows) == 3
    assert set(schema_rows[0]) == {"address", "amount", "token", "window_days", "source_exchange", "confidence",
                                   "tx_hash", "entry_address", "time"}
    assert schema_rows[0]["token"] == "USDT"


def test_live_trace_with_stale_inflow_warns(not_frozen):
    live = json.loads(json.dumps(FIXTURE))
    live["replay"] = False
    w = Watchlist()
    w.add_trace(live)
    r = check_mod.check("ethereum", A1, watch=w)
    assert r["decision"] == "warn" and r["evidence"]["rule_fired"] == "stale_inflow"


UNIVERSAL_ROUTER = "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad"


def test_infra_victim_and_hot_wallet_always_allowed(wl, not_frozen):
    wl.add_reports([{"address": BINANCE14, "chain": "ethereum", "reporter": "a", "tx_hash": "0x1"},
                    {"address": BINANCE14, "chain": "ethereum", "reporter": "b", "tx_hash": "0x2"}])
    for addr, rule in ((UNIVERSAL_ROUTER, "infra"), (VICTIM, "no_data"), (BINANCE14, "exchange")):
        r = check_mod.check("ethereum", addr, watch=wl)
        assert (r["decision"], r["evidence"]["rule_fired"]) == ("allow", rule), addr


def test_poison_and_fake_usdt_recipients_are_not_listed(wl, not_frozen):
    # the engine drops zero-value and non-USDT-contract transfers, so their counterparties never
    # become trace nodes; check() must answer allow / no data for them
    poison = "0xcf9bbfa762ef5a84ba3d25350de941a6db485099"  # lookalike of A-1
    r = check_mod.check("ethereum", poison, watch=wl)
    assert r["decision"] == "allow" and r["evidence"]["rule_fired"] == "no_data"


def test_evidence_is_typed_and_fast(wl, not_frozen):
    r = check_mod.check("ethereum", A1, watch=wl)
    ev = r["evidence"]
    assert set(ev) >= {"watchlist_version", "rule_fired", "case_ids", "label", "path", "victim_inflow_usdt",
                       "frozen", "chainabuse", "expires_at", "disclaimer"}
    assert ev["disclaimer"] == "reported, not proven"
    assert ev["path"][0]["from"] == VICTIM and len(ev["path"]) <= 4
    assert ev["elapsed_ms"] < 50


def test_watchlist_round_trips_to_disk(wl, tmp_path):
    p = tmp_path / "watchlist.json"
    wl.save(p)
    w2 = Watchlist()
    w2.load(p)
    assert w2.lookup("ethereum", A1)["cases"] == ["fixture-case-1"]
    assert w2.version() == wl.version()


def test_contracts_are_never_entry_addresses(monkeypatch):
    rfq = "0x91c986709bb4fe0763edf8e2690ee9d5019bea4a"  # Tokenlon RFQ v2, sends into A-1 in the replay

    def fake_transfers(ch, address, token="USDT", as_of=None, after=None):
        if address == A1:
            return [{"from": rfq, "to": A1, "amount": 9000.0, "time": "2024-05-02T00:00:00Z", "tx_hash": "0xr"}]
        if address == rfq:
            return [{"from": PAYER, "to": rfq, "amount": 500.0, "time": "2024-05-02T00:00:00Z", "tx_hash": "0xq"}]
        return []

    monkeypatch.setattr(chain, "get_transfers", fake_transfers)
    monkeypatch.setattr(chain, "is_contract", lambda c, a: a == rfq)
    assert all(r["entry_address"] != rfq for r in op_mod.payments(FIXTURE, window_days=7))


# ------------------------------------------------------------------ REVIEW_TEAM security-public-4 / -5

@pytest.mark.parametrize("exc", [chain.ChainAPIError("https://eth-mainnet.g.alchemy.com/v2/SECRETKEY123 down"),
                                 chain.CacheMiss("offline")])
def test_unknown_freeze_state_warns_never_allows(wl, monkeypatch, exc):
    def boom(c, a, **k):
        raise exc
    monkeypatch.setattr(chain, "freeze_status", boom)
    r = check_mod.check("ethereum", "0x2222222222222222222222222222222222222222", watch=wl)
    assert r["decision"] == "warn" and r["evidence"]["rule_fired"] == "freeze_unknown"
    assert "SECRETKEY123" not in json.dumps(r)


def test_check_route_status_codes_and_no_leaks(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hound.watch import routes
    app = FastAPI()
    app.include_router(routes.router)
    c = TestClient(app)
    assert c.get("/check?chain=ethereum&address=not-an-address").status_code == 400

    def offline(*a, **k):
        raise chain.CacheMiss("offline")
    monkeypatch.setattr(routes, "check", offline)
    assert c.get(f"/check?chain=ethereum&address={A1}").status_code == 503

    def leaky(*a, **k):
        raise chain.ChainAPIError("https://eth-mainnet.g.alchemy.com/v2/SECRETKEY123 timeout")
    monkeypatch.setattr(routes, "check", leaky)
    r = c.get(f"/check?chain=ethereum&address={A1}")
    assert r.status_code == 502 and "SECRETKEY123" not in r.text


def test_busy_endpoints_and_contracts_are_never_listed(monkeypatch, not_frozen):
    t = json.loads(json.dumps(FIXTURE))
    busy = "0x07964f135f276412b3182a3b2407b8dd45000000"  # real >5k-transfer contract from a live trace
    t["nodes"].append({"address": busy, "chain": "ethereum", "kind": "holding", "depth": 4})
    t["edges"].append({"from": HOP3, "to": busy, "token": "USDT", "amount": 500, "attributed_amount": 500,
                       "tx_hashes": ["0xb"], "first_time": "2024-05-04T00:00:00Z",
                       "last_time": "2024-05-04T00:00:00Z", "hop": 4, "confidence": 0.95, "method": "direct"})
    t["endpoints"] = [{"address": busy, "reason": "high_volume"}]
    w = Watchlist()
    w.add_trace(t)
    assert w.lookup("ethereum", busy) is None
    monkeypatch.setattr(chain, "is_contract", lambda c, a: a == A1)
    w2 = Watchlist()
    w2.add_trace(FIXTURE)
    assert w2.lookup("ethereum", A1) is None and w2.lookup("ethereum", HOP2) is not None


def test_deposit_address_sweeping_into_a_hot_wallet_is_never_listed(not_frozen):
    dep, cb10 = "0x2f1cf3ddb946bcc6746d0612b86cb4beda3d8fa4", "0xa9d1e08c7793af67e9d92fe308d5697fb81d3e43"
    t = {"trace_id": "t-dep", "case_id": "c-dep", "replay": False,
         "nodes": [{"address": VICTIM, "chain": "ethereum", "kind": "victim", "depth": 0},
                   {"address": dep, "chain": "ethereum", "kind": "intermediate", "depth": 1},
                   {"address": cb10, "chain": "ethereum", "kind": "exchange_hot", "depth": 2}],
         "edges": [{"from": VICTIM, "to": dep, "amount": 96028.85, "attributed_amount": 96028.85, "confidence": 1.0,
                    "last_time": "2026-10-08T15:45:23Z"},
                   {"from": dep, "to": cb10, "amount": 96028.85, "attributed_amount": 96028.85, "confidence": 1.0,
                    "last_time": "2026-10-08T15:49:11Z"}],
         "endpoints": [{"address": cb10, "reason": "exchange"}]}
    w = Watchlist()
    w.add_trace(t)
    assert w.lookup("ethereum", dep) is None
    assert check_mod.check("ethereum", dep, watch=w)["decision"] == "allow"


# ---------------------------------------------------------------- REVIEW_TEAM_R2 (watchlist inflow)

V = "0x" + "11" * 20
E1, E2, LOOP, FIN = ("0x" + c * 40 for c in "abcd")


def _r2_trace(case_id="r2-case", trace_id="r2-trace"):
    """Victim sends ETH to E1 (swapped to 1,000 USDT, seed s1) and 500 USDT to E2 (seed s2).
    E1 -> LOOP -> E1 is a laundering loop; everything ends at FIN."""
    def edge(a, b, token, amt, by_seed, conf=1.0):
        return {"from": a, "to": b, "token": token, "amount": amt, "attributed_amount": amt,
                "attributed_by_seed": by_seed, "tx_hashes": ["0x" + "e" * 64], "confidence": conf,
                "last_time": "2024-05-01T00:00:00Z", "method": "fifo"}
    node = lambda a, kind, pc: {"address": a, "chain": "ethereum", "kind": kind, "depth": 1, "path_confidence": pc}
    return {"trace_id": trace_id, "case_id": case_id, "replay": True,
            "seeds": [{"seed_id": "s1", "token": "ETH", "amount": 0.3}, {"seed_id": "s2", "token": "USDT", "amount": 500.0}],
            "nodes": [node(V, "victim", 1.0), node(E1, "intermediate", 1.0), node(E2, "intermediate", 0.85),
                      node(LOOP, "intermediate", 0.9), node(FIN, "holding", 1.0)],
            "edges": [edge(V, E1, "ETH", 0.3, {"s1": 0.3}), edge(V, E2, "USDT", 500.0, {"s2": 500.0}),
                      edge(E1, LOOP, "USDT", 1000.0, {"s1": 1000.0}), edge(LOOP, E1, "USDT", 1000.0, {"s1": 1000.0}),
                      edge(E1, FIN, "USDT", 1000.0, {"s1": 1000.0}), edge(E2, FIN, "USDT", 500.0, {"s2": 500.0})],
            "swaps": {"resolved": [{"address": E1, "recipient": E1, "eth_out": 0.3, "usdt_in": 1000.0,
                                    "victim_eth": {"s1": 0.3}, "victim_usdt": {"s1": 1000.0}}]},
            "endpoints": [{"address": FIN, "reason": "holding", "victim_inflow": 1500.0}]}


@pytest.fixture
def no_chain(monkeypatch):
    monkeypatch.setattr(chain, "label", lambda c, a, **k: None)
    monkeypatch.setattr(chain, "is_contract", lambda c, a: False)


def test_rerunning_a_case_never_inflates_victim_money(no_chain):
    w = Watchlist()
    for i in range(3):  # preloaded example + two rehearsals of the same case, new trace ids
        w.add_trace(_r2_trace(trace_id=f"run-{i}"))
    assert w.lookup("ethereum", FIN)["victim_inflow"] == pytest.approx(1500.0)
    w.add_trace(_r2_trace(case_id="other-case"))  # a second victim case does add
    assert w.lookup("ethereum", FIN)["victim_inflow"] == pytest.approx(3000.0)


def test_eth_is_never_summed_as_usdt_and_swaps_count(no_chain):
    w = Watchlist()
    w.add_trace(_r2_trace())
    # E1 got 0.3 ETH from the victim: it counts the 1,000 USDT that ETH swapped into, not "0.3 USDT"
    # and not the loop's second pass (cap = 1,000 for seed s1)
    assert w.lookup("ethereum", E1)["victim_inflow"] == pytest.approx(1000.0)
    assert w.lookup("ethereum", E2)["victim_inflow"] == pytest.approx(500.0)
    assert w.lookup("ethereum", LOOP)["victim_inflow"] == pytest.approx(1000.0)


def test_confidence_is_the_engines_node_path_confidence(no_chain, not_frozen):
    w = Watchlist()
    w.add_trace(_r2_trace())
    r = check_mod.check("ethereum", E2, watch=w)
    assert r["confidence"] == 0.85 and "path confidence 0.85" in " ".join(r["reasons"])


def test_reset_drops_the_saved_watchlist_and_old_files_are_ignored(no_chain, not_frozen, monkeypatch, tmp_path):
    from hound.watch import watchlist as wl_mod
    monkeypatch.setenv("HOUND_TRACE_DIRS", str(tmp_path / "none"))
    wl_mod.reset()
    wl_mod.register_trace(_r2_trace())
    assert wl_mod.watchlist_file().exists()
    assert check_mod.check("ethereum", FIN, watch=wl_mod.default())["decision"] == "hold"
    wl_mod.reset()
    assert not wl_mod.watchlist_file().exists()
    assert check_mod.check("ethereum", FIN, watch=wl_mod.default())["evidence"]["rule_fired"] == "no_data"
    # a pre-fix file (per-run sums, no format) is ignored rather than trusted
    wl_mod.watchlist_file().write_text(json.dumps({"entries": [
        {"chain": "ethereum", "address": FIN, "cases": ["x"], "victim_inflow": 999911.94, "confidence": 1.0}]}))
    w = Watchlist()
    assert w.load(wl_mod.watchlist_file()) == 0 and w.lookup("ethereum", FIN) is None
    wl_mod.reset()


def test_path_hops_say_which_token_they_are_in(no_chain, not_frozen):
    w = Watchlist()
    w.add_trace(_r2_trace())
    hops = check_mod.check("ethereum", E1, watch=w)["evidence"]["path"]
    assert hops[0]["from"] == V and (hops[0]["amount"], hops[0]["token"]) == (0.3, "ETH")
    hops = check_mod.check("ethereum", FIN, watch=w)["evidence"]["path"]
    assert hops[-1]["token"] == "USDT"


def test_path_hop_counts_each_victim_dollar_once(no_chain, not_frozen):
    t = _r2_trace()
    # the loop's second pass makes the engine's per-seed figure on E1 -> LOOP twice the send
    t["edges"][2]["attributed_amount"] = 2000.0
    t["edges"][2]["attributed_by_seed"] = {"s1": 2000.0}
    w = Watchlist()
    w.add_trace(t)
    hops = check_mod.check("ethereum", LOOP, watch=w)["evidence"]["path"]
    assert [h["amount"] for h in hops if h["to"] == LOOP] == [1000.0]


def test_victim_paying_from_an_exchange_never_fetches_the_exchange(monkeypatch):
    """Intake screenshots are often exchange withdrawals: the 'victim' node is the exchange hot
    wallet. Its history is every customer's; other payers must not fetch it."""
    t = json.loads(json.dumps(FIXTURE))
    for n in t["nodes"]:
        if n["address"] == VICTIM:
            n["address"] = COINBASE10
    for e in t["edges"]:
        if e["from"] == VICTIM:
            e["from"] = COINBASE10
    fetched = []

    def fake_transfers(ch, address, token="USDT", as_of=None, after=None):
        fetched.append(address)
        return []

    monkeypatch.setattr(chain, "get_transfers", fake_transfers)
    monkeypatch.setattr(chain, "get_native_txs", lambda *a, **k: [], raising=False)
    op_mod.payments(t, window_days=7)
    assert COINBASE10 not in fetched and A1 in fetched
