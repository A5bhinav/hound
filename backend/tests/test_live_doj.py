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
