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
                        lambda c, a: {"is_frozen": False, "frozen_at": None, "freeze_tx": None})


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
    assert r["evidence"]["watchlist"]["cases"] == ["fixture-case-1"]
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
    monkeypatch.setattr(chain, "freeze_status", lambda c, a: {"is_frozen": True, "frozen_at": "2024-06-21T14:53:11Z",
                                                              "freeze_tx": "0x5b12"})
    r = check_mod.check("ethereum", A7, watch=wl)
    assert r["decision"] == "hold"
    assert r["evidence"]["frozen"]["freeze_tx"] == "0x5b12"


def test_unknown_allowed(wl, not_frozen):
    r = check_mod.check("ethereum", "0x2222222222222222222222222222222222222222", watch=wl)
    assert r["decision"] == "allow"


def test_freeze_api_down_still_answers(wl, monkeypatch):
    def boom(c, a):
        raise chain.ChainAPIError("rpc down")
    monkeypatch.setattr(chain, "freeze_status", boom)
    r = check_mod.check("ethereum", A1, watch=wl)
    assert r["decision"] == "hold"
    assert "freeze_check_error" in r["evidence"]


# ------------------------------------------------------------------ other payers

PAYER = "0x3333333333333333333333333333333333333333"
PASS_THROUGH = "0x5555555555555555555555555555555555555555"
COINBASE10 = "0xa9d1e08c7793af67e9d92fe308d5697fb81d3e43"


def test_other_payers_count_payments_into_the_entry_layer(monkeypatch):
    def fake_transfers(ch, address, token="USDT", as_of=None, after=None):
        if token != "USDT":
            return []
        if address == A1:  # first-swap layer: an outside pass-through sends in
            return [{"from": PASS_THROUGH, "to": A1, "amount": 4000.0, "time": "2024-05-02T00:00:00Z",
                     "tx_hash": "0xs1", "token": "USDT"}]
        if address == VICTIM:  # depth-0 entry node
            return [{"from": COINBASE10, "to": VICTIM, "amount": 300.0, "time": "2024-05-02T00:00:00Z",
                     "tx_hash": "0xc1", "token": "USDT"},
                    {"from": COINBASE10, "to": VICTIM, "amount": 500.0, "time": "2024-05-03T00:00:00Z",
                     "tx_hash": "0xc2", "token": "USDT"},
                    {"from": PAYER, "to": VICTIM, "amount": 50.0, "time": "2024-05-03T00:00:00Z",
                     "tx_hash": "0xdust", "token": "USDT"}]
        if address == PASS_THROUGH:
            return [{"from": COINBASE10, "to": PASS_THROUGH, "amount": 4100.0, "time": "2024-05-01T12:00:00Z",
                     "tx_hash": "0xc3", "token": "USDT"},
                    {"from": HOP2, "to": PASS_THROUGH, "amount": 900.0, "time": "2024-05-01T12:00:00Z",
                     "tx_hash": "0xinternal", "token": "USDT"}]
        return []

    monkeypatch.setattr(chain, "get_transfers", fake_transfers)
    rows = op_mod.payments(FIXTURE, window_days=7)
    assert [r["tx_hash"] for r in rows] == ["0xc3", "0xc1", "0xc2"]  # dust and trace-internal excluded
    assert {r["entry_address"] for r in rows} == {VICTIM, PASS_THROUGH}
    assert all(r["source_exchange"] == "Coinbase" for r in rows)
    assert op_mod.summary(rows)["text"] == "3 payments in from 1 exchange into 2 entry addresses"
    schema_rows = op_mod.other_payers(FIXTURE, window_days=7)
    assert len(schema_rows) == 3
    assert set(schema_rows[0]) == {"address", "amount", "window_days", "source_exchange", "confidence"}
