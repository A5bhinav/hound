"""Offline tests for chain/: cache, retries, parsing, holdout guard. No network."""

import json
import time

import httpx
import pytest

from hound.chain import cache, eth, holdout, labels, net


# ------------------------------------------------------------------ cache

def test_cache_hit_and_ttl(monkeypatch):
    calls = []
    fetch = lambda: calls.append(1) or {"v": len(calls)}
    assert cache.cached("t", {"a": 1}, fetch, ttl=60) == {"v": 1}
    assert cache.cached("t", {"a": 1}, fetch, ttl=60) == {"v": 1}
    assert len(calls) == 1
    # expired -> refetch
    entry = cache.read("t", {"a": 1})
    cache.write("t", {"a": 1}, entry["value"])
    p = cache._path("t", {"a": 1})
    data = json.loads(p.read_text()); data["saved_at"] -= 120; p.write_text(json.dumps(data))
    assert cache.cached("t", {"a": 1}, fetch, ttl=60) == {"v": 2}


def test_empty_results_expire_even_with_forever_ttl():
    cache.cached("t", {"e": 1}, lambda: [], ttl=None, is_empty=lambda v: v == [])
    p = cache._path("t", {"e": 1})
    data = json.loads(p.read_text()); data["saved_at"] -= cache.EMPTY_TTL + 1; p.write_text(json.dumps(data))
    assert cache.cached("t", {"e": 1}, lambda: ["fresh"], ttl=None, is_empty=lambda v: v == []) == ["fresh"]


def test_offline_mode(monkeypatch):
    cache.cached("t", {"o": 1}, lambda: 5, ttl=1)
    p = cache._path("t", {"o": 1})
    data = json.loads(p.read_text()); data["saved_at"] -= 999; p.write_text(json.dumps(data))
    monkeypatch.setenv("HOUND_OFFLINE", "1")
    assert cache.cached("t", {"o": 1}, lambda: pytest.fail("network in offline mode"), ttl=1) == 5
    with pytest.raises(cache.CacheMiss):
        cache.cached("t", {"o": 2}, lambda: 1, ttl=None)


# ------------------------------------------------------------------ retries

def _mock_client(monkeypatch, handler):
    monkeypatch.setattr(net, "_client", httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(net.time, "sleep", lambda s: None)


def test_retries_429_then_succeeds(monkeypatch):
    n = {"i": 0}

    def handler(req):
        n["i"] += 1
        if n["i"] < 3:
            return httpx.Response(429, headers={"retry-after": "1"}, text="slow down")
        return httpx.Response(200, json={"ok": True})

    _mock_client(monkeypatch, handler)
    assert net.request_json("GET", "https://example.test/x") == {"ok": True}
    assert net.stats()["retries"] == 2


def test_long_rate_limit_raises_instead_of_sleeping(monkeypatch):
    _mock_client(monkeypatch, lambda req: httpx.Response(429, headers={"x-ratelimit-reset": "1856773"}))
    with pytest.raises(net.RateLimited):
        net.request_json("GET", "https://example.test/x")


def test_gives_up_loudly(monkeypatch):
    _mock_client(monkeypatch, lambda req: httpx.Response(503, text="down"))
    with pytest.raises(net.ChainAPIError, match="failed after"):
        net.request_json("GET", "https://example.test/x", retries=2)


def test_4xx_is_not_retried(monkeypatch):
    _mock_client(monkeypatch, lambda req: httpx.Response(400, text="bad address"))
    with pytest.raises(net.ChainAPIError, match="HTTP 400"):
        net.request_json("GET", "https://example.test/x")
    assert net.stats()["retries"] == 0


# ------------------------------------------------------------------ parsing

A7 = "0xa1770ead287dc8e91631a7a323390d5b744f0021"
SENDER = "0x58e99d9413bb6ce05748a84f76e5fff4bb2d0dcb"


def _log(frm, to, raw, block, li, ts):
    return {"address": eth.USDT, "topics": [eth.TRANSFER_TOPIC, "0x" + frm[2:].rjust(64, "0"),
                                            "0x" + to[2:].rjust(64, "0")],
            "data": hex(raw), "blockNumber": hex(block), "logIndex": hex(li), "blockTimestamp": hex(ts),
            "transactionHash": "0x" + f"{block:064x}"}


def test_rpc_transfers_parse_dedupe_and_filter(monkeypatch):
    t0 = 1716000000
    incoming = [_log(SENDER, A7, 150_000 * 10**6, 100, 1, t0), _log(A7, A7, 5 * 10**6, 101, 2, t0 + 60)]
    outgoing = [_log(A7, SENDER, 1, 102, 3, t0 + 120), _log(A7, A7, 5 * 10**6, 101, 2, t0 + 60)]

    def fake_rpc_logs(flt, from_block, to_block=None, cap=None, on_cap=None):
        return outgoing if flt["topics"][1] else incoming

    monkeypatch.setattr(eth, "rpc_logs", fake_rpc_logs)
    monkeypatch.setenv("HOUND_ETH_TRANSFER_SOURCES", "rpc")
    out = eth.get_transfers(A7, token="USDT")
    assert [t["amount"] for t in out] == [150000.0, 5.0, 0.000001]  # self-transfer counted once
    assert out[0] == {**out[0], "from": SENDER, "to": A7, "token": "USDT", "block": 100,
                      "time": "2024-05-18T02:40:00Z", "log_index": 1}
    assert len(eth.get_transfers(A7, token="USDT", after="2024-05-18T02:41:01Z")) == 1


def test_too_many_transfers(monkeypatch):
    def fake_rpc_logs(flt, from_block, to_block=None, cap=None, on_cap=None):
        raise on_cap(cap + 1)

    monkeypatch.setattr(eth, "rpc_logs", fake_rpc_logs)
    monkeypatch.setenv("HOUND_ETH_TRANSFER_SOURCES", "rpc")
    with pytest.raises(net.TooManyTransfers):
        eth.get_transfers(A7, token="USDT")


def test_all_sources_fail_raises(monkeypatch):
    def boom(*a, **k):
        raise net.ChainAPIError("down")

    monkeypatch.setattr(eth, "rpc_logs", boom)
    monkeypatch.setattr(eth, "_transfers_v2", boom)
    monkeypatch.setattr(eth, "_transfers_v1", boom)
    monkeypatch.setenv("HOUND_ETH_TRANSFER_SOURCES", "rpc,blockscout_v2,blockscout")
    with pytest.raises(net.ChainAPIError, match="could not get transfers"):
        eth.get_transfers(A7, token="USDT")


def test_bad_address_rejected():
    with pytest.raises(ValueError):
        eth.get_transfers("0x123", token="USDT")


# ------------------------------------------------------------------ holdout + labels

def test_holdout_matches_full_and_truncated():
    assert holdout.matches(A7.upper().replace("0X", "0x"))
    # truncated "e79…c2d6ad0" from the complaint
    assert holdout.matches("0xe79" + "0" * 30 + "c2d6ad0")
    assert not holdout.matches("0x28c6c06298d514db089934071355e5743bf21d60")


def test_label_db_has_no_holdout_addresses():
    """The DOJ match must stay blind: no complaint address may be in the label DB."""
    labels.reload()
    db = labels.all_labels("ethereum")
    assert db, "label DB is empty: run python -m hound.chain.build_labels"
    leaks = [a for a in db if holdout.matches(a)]
    assert leaks == []


def test_label_db_refuses_to_load_with_a_holdout_address(monkeypatch):
    labels.reload()
    monkeypatch.setitem(labels.MANUAL, "ethereum", {A7: {"name": "leak", "kind": "service", "source": "test"}})
    with pytest.raises(holdout.HoldoutViolation):
        labels.label("ethereum", A7)
    monkeypatch.setitem(labels.MANUAL, "ethereum", {})
    labels.reload()


def test_known_labels():
    assert labels.label("ethereum", "0x28C6c06298d514Db089934071355E5743bf21d60")["kind"] == "exchange_hot"
    assert labels.is_exchange("ethereum", "0x28c6c06298d514db089934071355e5743bf21d60")
    torn = labels.label("ethereum", "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf")
    assert torn["kind"] in ("ofac", "service")
    assert labels.label("ethereum", A7) is None
