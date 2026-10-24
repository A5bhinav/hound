"""Live checks against the real DOJ case (US v. 4,340,000 Tether, N.D. Ohio 1:25-cv-00386).

    HOUND_LIVE=1 .venv/bin/python -m pytest -m live -q

These are the "done" criteria for brief §9.2. They also warm cache/ for the demo.
"""

import pytest

from hound import chain
from hound.watch import check
from hound.watch.watchlist import Watchlist

pytestmark = pytest.mark.live

A7 = "0xa1770ead287dc8e91631a7a323390d5b744f0021"
A8 = "0x4e5cda8f0d772ac57e947545192a0657ad47abb5"
A9 = "0xafd770d8898a0e323c607fe91358345e7b2378a5"
BINANCE14 = "0x28c6c06298d514db089934071355e5743bf21d60"


def test_freeze_events_return_the_three_doj_freezes():
    ev = {e["address"]: e for e in chain.freeze_events("ethereum", after="2024-06-20T00:00:00Z",
                                                        before="2024-06-26T00:00:00Z")}
    assert ev[A7]["block"] == 20140818
    assert ev[A8]["block"] == 20170086
    assert ev[A9]["block"] == 20140808
    assert ev[A7]["frozen_at"].startswith("2024-06-21")
    assert ev[A8]["frozen_at"].startswith("2024-06-25")


def test_freeze_status_and_destroyed_funds():
    s = chain.freeze_status("ethereum", A7)
    assert s["is_frozen"] is True
    assert s["freeze_tx"] == "0x5b124d778136157b2f9e27e5fc6179780598288a9f36be7bd558301068f48b7a"
    assert s["destroyed_usdt"] == 4340000.0  # the case's 4,340,000 USDT
    assert chain.freeze_status("ethereum", BINANCE14)["is_frozen"] is False


def test_a7_transfers_net_to_the_seized_amount():
    t = chain.get_transfers("ethereum", A7, token="USDT", include_zero=True)
    assert len(t) == 41
    # 3 of them are zero-value address-poisoning transfers, dropped by default (AUDIT N2)
    assert len(chain.get_transfers("ethereum", A7, token="USDT")) == 38
    inflow = sum(x["amount"] for x in t if x["to"] == A7)
    outflow = sum(x["amount"] for x in t if x["from"] == A7)
    assert round(inflow - outflow, 6) == 4340000.0
    assert chain.get_balance("ethereum", A7) == 0.0  # destroyed by Tether after the freeze


def test_exchange_hot_wallet_is_too_busy_to_trace():
    with pytest.raises(chain.TooManyTransfers):
        chain.get_transfers("ethereum", BINANCE14, token="USDT")


def test_check_holds_a7_and_allows_binance():
    wl = Watchlist()
    r = check(chain_name="ethereum", address=A7, watch=wl)
    assert r["decision"] == "hold"
    assert r["evidence"]["frozen"]["freeze_tx"].startswith("0x5b124d")
    assert check("ethereum", BINANCE14, watch=wl)["decision"] == "allow"


def test_stats_counted():
    chain.get_transfers("ethereum", A7, token="USDT")
    s = chain.stats()
    assert s["api_calls"] + s["cache_hits"] > 0


D95 = "0xd95da710ca21c985799a168109db702044be2cd4"
A1 = "0xcf9bbfa762ef5a84ba3d25350de941a6db485027"
CUTOFF = 20170085


def test_freeze_dump_and_as_of():
    s = chain.freeze_status("ethereum", A7)
    assert s["status"] == "destroyed" and s["frozen_block"] == 20140818
    assert s["destroyed_amount"] == 4340000.0 and s["destroyed_block"] == 21196374
    assert chain.freeze_status("ethereum", A7, as_of=20140817)["status"] == "none"
    assert chain.freeze_status("ethereum", A7, as_of=CUTOFF)["status"] == "frozen"


def test_balance_at_replay_cutoff():
    # today's balance is 0 (destroyed); at the cutoff A-7 held more than A.H.'s 314,657 (¶ 74)
    assert chain.get_balance("ethereum", A7, block=CUTOFF) >= 314657
    assert chain.get_balance("ethereum", A7) == 0.0


def test_native_txs_include_ah_sends_into_a1():
    txs = chain.get_native_txs("ethereum", D95, as_of=CUTOFF)
    sends = [t for t in txs if t["from"] == D95 and int(t["amount_wei"]) > 0]
    assert sends and all(set(t) >= {"tx_hash", "tx_index", "from", "to", "amount_wei", "gas_wei", "block", "time"}
                         for t in txs)
    assert all(t["block"] <= CUTOFF for t in txs)
    assert any(t["to"] == A1 for t in sends)


def test_metadata_labels_crypto_com():
    lb = chain.label("ethereum", "0x6262998ced04146fa42253a5c0af90ca02dfd2a3")
    assert lb["kind"] == "exchange_hot" and lb["source"] == "blockscout_metadata"


def test_replay_runs_offline_from_the_committed_snapshot(tmp_path, monkeypatch):
    """A fresh clone (empty cache/) replays the DOJ case with zero network calls."""
    import json
    from hound.chain.cache import REPO_ROOT
    from hound.engine.trace import run_trace
    monkeypatch.setenv("HOUND_CACHE_DIR", str(tmp_path / "empty"))
    monkeypatch.setenv("HOUND_CACHE_MODE", "readonly")
    chain.reset_stats()
    trace = run_trace(json.loads((REPO_ROOT / "examples" / "ohnd_replay.case.json").read_text()))
    assert trace["status"] == "done"
    assert {A7, A9} <= {e["address"] for e in trace["endpoints"]}
    assert chain.stats()["api_calls"] == 0
