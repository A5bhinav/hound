"""Offline tests for chain/: cache, retries, parsing, holdout guard. No network."""

import json
import time

import httpx
import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import holdout_guard as holdout  # noqa: E402
from hound.chain import cache, eth, labels, net  # noqa: E402


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
    assert db, "label DB is empty: run python backend/tools/build_labels.py"
    leaks = [a for a in db if holdout.matches(a)]
    assert leaks == []


def test_known_labels():
    assert labels.label("ethereum", "0x28C6c06298d514Db089934071355E5743bf21d60")["kind"] == "exchange_hot"
    assert labels.is_exchange("ethereum", "0x28c6c06298d514db089934071355e5743bf21d60")
    torn = labels.label("ethereum", "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf")
    assert torn["kind"] in ("sanctioned", "service")
    assert labels.label("ethereum", A7, network=False) is None


# ------------------------------------------------------------------ cache modes + snapshot

def test_readonly_mode_never_fetches(monkeypatch):
    monkeypatch.setenv("HOUND_CACHE_MODE", "readonly")
    with pytest.raises(cache.CacheMiss):
        cache.cached("t", {"r": 1}, lambda: pytest.fail("network in readonly"), ttl=None)


def test_prefer_cache_serves_stale_and_fetches_misses(monkeypatch):
    cache.cached("t", {"p": 1}, lambda: "old", ttl=1)
    p = cache._path("t", {"p": 1})
    data = json.loads(p.read_text()); data["saved_at"] -= 999; p.write_text(json.dumps(data))
    monkeypatch.setenv("HOUND_CACHE_MODE", "prefer_cache")
    assert cache.cached("t", {"p": 1}, lambda: "new", ttl=1) == "old"
    assert cache.cached("t", {"p": 2}, lambda: "fetched", ttl=1) == "fetched"


def test_bad_mode_is_loud(monkeypatch):
    monkeypatch.setenv("HOUND_CACHE_MODE", "sometimes")
    with pytest.raises(ValueError):
        cache.mode()


def test_api_keys_never_reach_cache_keys_or_files(monkeypatch):
    monkeypatch.setenv("ETHERSCAN_API_KEY", "SUPERSECRETKEY123")
    a = {"module": "account", "address": "0x1", "apikey": "SUPERSECRETKEY123"}
    b = {"module": "account", "address": "0x1"}
    assert cache.key(a) == cache.key(b)
    cache.cached("t", a, lambda: {"ok": 1}, ttl=None)
    assert "SUPERSECRETKEY123" not in cache._path("t", a).read_text()


def test_snapshot_pack_and_read(tmp_path, monkeypatch):
    from hound.chain import snapshot
    cache.cached("eth_rpc", {"method": "x"}, lambda: "0x1", ttl=None)
    out = tmp_path / "snap"
    assert snapshot.pack(out_dir=out) == {"eth_rpc": 1}
    monkeypatch.setattr(cache, "SNAPSHOT_DIR", out)
    cache.reload_snapshot()
    monkeypatch.setenv("HOUND_CACHE_DIR", str(tmp_path / "empty"))
    monkeypatch.setenv("HOUND_CACHE_MODE", "readonly")
    assert cache.cached("eth_rpc", {"method": "x"}, lambda: pytest.fail("network"), ttl=None) == "0x1"
    cache.reload_snapshot()


def test_snapshot_refuses_secrets(tmp_path, monkeypatch):
    from hound.chain import snapshot
    cache.cached("eth_rpc", {"method": "y"}, lambda: "leaked-SECRETVALUE99", ttl=None)
    monkeypatch.setenv("SOME_API_KEY", "leaked-SECRETVALUE99")
    with pytest.raises(RuntimeError, match="secret"):
        snapshot.pack(out_dir=tmp_path / "snap")


def test_rate_limit_body_with_http_200_raises_and_caches_nothing(monkeypatch):
    """The A-8 silent zero: a 200 'Max rate limit' body must never become a cached empty result."""
    body = {"status": "0", "message": "NOTOK", "result": "Max rate limit reached"}
    _mock_client(monkeypatch, lambda req: httpx.Response(200, json=body))
    params = {"module": "account", "action": "tokentx", "address": A7}
    with pytest.raises(net.ChainAPIError):
        eth.explorer(params, sources=["blockscout"])
    assert cache.read("eth_v1", {"source": "blockscout", **params}) is None


def test_infra_and_sanctioned_kinds():
    labels.reload()
    ur = labels.label("ethereum", "0x3fC91A3afd70395Cd496C647d5a6CC9D4B2b7FAD", network=False)
    assert ur["kind"] == "infra"
    assert labels.label("ethereum", eth.USDT, network=False)["kind"] == "infra"
    assert labels.label("ethereum", "0x7f367cc41522ce07553e823bf3be79a889debe1b", network=False)["kind"] == "sanctioned"


def test_range_too_big_is_remembered_for_readonly_replays(monkeypatch):
    calls = []

    def too_big(url, method, params):
        calls.append(url)
        raise eth.RangeTooBig("query returned more than 10000 results")

    monkeypatch.setattr(eth, "_rpc_once", too_big)
    flt = [{"address": eth.USDT, "fromBlock": "0x1", "toBlock": "0x2"}]
    with pytest.raises(eth.RangeTooBig):
        eth.rpc("eth_getLogs", flt, ttl=None, urls=["https://a.test"])
    monkeypatch.setenv("HOUND_CACHE_MODE", "readonly")
    with pytest.raises(eth.RangeTooBig):  # not CacheMiss: the split is replayed offline
        eth.rpc("eth_getLogs", flt, ttl=None, urls=["https://a.test"])
    assert len(calls) == 1


def test_snapshot_refuses_live_case_addresses(tmp_path, monkeypatch):
    from hound.chain import snapshot
    live = "0x" + "7830c87c" + "0" * 25 + "fa86f43"
    cache.cached("eth_rpc", {"method": "z"}, lambda: {"to": live}, ttl=None)
    (cache.cache_dir()).mkdir(parents=True, exist_ok=True)
    (cache.cache_dir() / "live_addresses.json").write_text(json.dumps([live]))
    with pytest.raises(RuntimeError, match="live-case"):
        snapshot.pack(out_dir=tmp_path / "snap")


def test_tx_sends_rejects_bad_hash():
    with pytest.raises(ValueError):
        eth.tx_sends("0x1234")


def test_tx_sends_outage_is_not_a_bad_hash(monkeypatch):
    """Every RPC down -> ChainAPIError (intake says 'try again'); every RPC null -> ValueError (bad hash)."""
    def down(*a, **k):
        raise net.ChainAPIError("HTTP 503")
    monkeypatch.setattr(eth, "request_json", down)
    with pytest.raises(net.ChainAPIError) as ei:
        eth.tx_sends("0x" + "ab" * 32)
    assert not isinstance(ei.value, ValueError) and not isinstance(ei.value, eth.NullResult)

    monkeypatch.setattr(eth, "request_json", lambda *a, **k: {"jsonrpc": "2.0", "id": 1, "result": None})
    with pytest.raises(ValueError, match="not found on any RPC"):
        eth.tx_sends("0x" + "cd" * 32)


def test_tx_sends_mixed_null_and_outage_is_an_outage(monkeypatch):
    answers = iter([{"jsonrpc": "2.0", "id": 1, "result": None}])

    def first_null_then_down(*a, **k):
        try:
            return next(answers)
        except StopIteration:
            raise net.ChainAPIError("HTTP 503")
    monkeypatch.setattr(eth, "request_json", first_null_then_down)
    monkeypatch.setattr(eth, "ETH_ARCHIVE_RPC_URLS", ["https://a.example"])
    monkeypatch.setattr(eth, "ETH_RPC_URLS", ["https://a.example", "https://b.example"])
    with pytest.raises(net.ChainAPIError) as ei:
        eth.tx_sends("0x" + "ef" * 32)
    assert not isinstance(ei.value, eth.NullResult)


def test_rpc_errors_never_include_url_paths(monkeypatch):
    _mock_client(monkeypatch, lambda req: httpx.Response(200, json={"jsonrpc": "2.0", "id": 1,
                                                                    "error": {"message": "boom"}}))
    with pytest.raises(net.ChainAPIError) as ei:
        eth._rpc_once("https://eth-mainnet.g.alchemy.com/v2/SECRETKEY123", "eth_call", [])
    assert "SECRETKEY123" not in str(ei.value)
    _mock_client(monkeypatch, lambda req: httpx.Response(503, text="down"))
    with pytest.raises(net.ChainAPIError) as ei:
        net.request_json("POST", "https://eth-mainnet.g.alchemy.com/v2/SECRETKEY123", retries=0)
    assert "SECRETKEY123" not in str(ei.value)


def test_etherscan_getlogs_pages_by_block_window_and_parses_zero(monkeypatch):
    """1,000-row pages restart at the last block, dedupe on (tx, logIndex); Etherscan writes 0 as "0x"."""
    monkeypatch.setenv("ETHERSCAN_API_KEY", "k")
    me = "0x" + A7[2:].rjust(64, "0")

    def row(i, block, frm, to):
        return {"address": eth.USDT, "topics": [eth.TRANSFER_TOPIC, "0x" + frm[2:].rjust(64, "0"),
                                                "0x" + to[2:].rjust(64, "0")],
                "data": hex(10**6), "blockNumber": hex(block), "timeStamp": hex(1716000000 + i),
                "logIndex": "0x" if i == 0 else hex(i), "transactionIndex": "0x",
                "transactionHash": "0x" + f"{i:064x}"}

    first = [row(i, 100 + i // 10, SENDER, A7) for i in range(1000)]  # last block 199
    second = [row(i, 199, SENDER, A7) for i in range(990, 1003)]  # re-fetch of block 199 + 3 new
    calls = []

    def fake_explorer(params, ttl=None, sources=None):
        calls.append((params.get("topic1"), params.get("topic2"), params["fromBlock"]))
        if params.get("topic2") == me:
            return {"result": first if params["fromBlock"] == eth.USDT_DEPLOY_BLOCK else second}
        return {"result": []}

    monkeypatch.setattr(eth, "explorer", fake_explorer)
    out = eth._transfers_etherscan_logs(A7, eth.USDT)
    assert len(out) == 1003  # 1000 + 3 new, the 10 overlapping rows deduped
    assert out[0]["log_index"] == 0 and out[0]["tx_index"] == 0
    assert (None, me, 199) in calls


def test_etherscan_is_primary_only_when_keyed(monkeypatch):
    seen = []
    monkeypatch.setattr(eth, "_transfers_etherscan_logs", lambda a, c: seen.append("es") or [])
    monkeypatch.setattr(eth, "_transfers_rpc", lambda *a: seen.append("rpc") or [])
    monkeypatch.delenv("HOUND_ETH_TRANSFER_SOURCES", raising=False)
    monkeypatch.setenv("ETHERSCAN_API_KEY", "k")
    eth.get_transfers(A7, token="USDT")
    monkeypatch.delenv("ETHERSCAN_API_KEY")
    eth.get_transfers(A7, token="USDT")
    assert seen == ["es", "rpc"]


def test_live_bundle_is_read_after_the_public_snapshot(tmp_path, monkeypatch):
    from hound.chain import snapshot
    live = "0x" + "2f1cf3dd" + "0" * 32
    cache.cached("eth_rpc", {"method": "live"}, lambda: {"to": live}, ttl=None)
    bundle = tmp_path / "cases_live" / "cache"
    monkeypatch.setattr(cache, "LIVE_SNAPSHOT_DIR", bundle)
    (cache.cache_dir() / "live_addresses.json").write_text(json.dumps([live]))
    with pytest.raises(RuntimeError, match="live-case"):  # never into the public snapshot
        snapshot.pack(out_dir=tmp_path / "public")
    assert snapshot.pack(out_dir=bundle, allow_live=True)["eth_rpc"] >= 1
    with pytest.raises(ValueError):  # allow_live only for the private bundle
        snapshot.pack(out_dir=tmp_path / "public", allow_live=True)
    cache.reload_snapshot()
    monkeypatch.setenv("HOUND_CACHE_DIR", str(tmp_path / "fresh-laptop"))
    monkeypatch.setenv("HOUND_CACHE_MODE", "readonly")
    assert cache.cached("eth_rpc", {"method": "live"}, lambda: pytest.fail("network"), ttl=None) == {"to": live}
    cache.reload_snapshot()


def test_snapshot_never_packs_the_server_cache(monkeypatch):
    from hound.chain import snapshot
    with pytest.raises(ValueError, match="server cache"):
        snapshot.pack(cache_root=cache.REPO_ROOT / "cache", out_dir=cache.REPO_ROOT / "cache" / "_never")


def test_readonly_falls_through_to_a_cached_source(monkeypatch):
    """Snapshot built without an Etherscan key, demo laptop has one: the Etherscan miss must fall
    back to the cached RPC data instead of failing the trace."""
    monkeypatch.setenv("ETHERSCAN_API_KEY", "k")
    monkeypatch.setenv("HOUND_CACHE_MODE", "readonly")
    row = {"tx_hash": "0x" + "a" * 64, "log_index": 0, "from": A7, "to": eth.USDT, "amount": 1.0,
           "block": 1, "time": "2024-05-01T00:00:00Z"}

    def miss(*a, **k):
        raise cache.CacheMiss("not cached")

    monkeypatch.setattr(eth, "_transfers_etherscan_logs", miss)
    monkeypatch.setattr(eth, "_transfers_rpc", lambda *a, **k: [row])
    assert eth.get_transfers(A7) == [row]
    monkeypatch.setattr(eth, "_transfers_rpc", miss)
    monkeypatch.setattr(eth, "_transfers_v2", miss)
    monkeypatch.setattr(eth, "_transfers_v1", miss)
    with pytest.raises(cache.CacheMiss):
        eth.get_transfers(A7)



def test_public_exchange_wallets_never_block_a_pack(tmp_path):
    from hound.chain import snapshot
    coinbase10 = "0xa9d1e08c7793af67e9d92fe308d5697fb81d3e43"
    cache.cached("eth_rpc", {"method": "cb"}, lambda: {"to": coinbase10}, ttl=None)
    (cache.cache_dir() / "live_addresses.json").write_text(json.dumps([coinbase10]))
    assert snapshot.pack(out_dir=tmp_path / "snap") == {"eth_rpc": 1}


def test_tron_freeze_lookup_never_pages_trongrid_in_a_request(tmp_path, monkeypatch):
    """The keyless TronGrid event log is ~58 pages at 1 req/s: /check must read the dump instead."""
    from hound.chain import freezes, tron
    monkeypatch.setattr(tron, "blacklist_history", lambda: pytest.fail("paged TronGrid inside a request"))
    freezes._MEMO.clear()
    monkeypatch.setattr(freezes, "TRON_DUMP_FILE", tmp_path / "missing.json")
    assert freezes._history("tron") == {}
    dump = tmp_path / "freezes_tron.json"
    ev = {"type": "added", "block": 1, "time": "2020-11-24T07:18:24Z", "tx": "ab", "log_index": 0}
    dump.write_text(json.dumps({"_meta": {}, "events": {"TMzn3oX7caFKbJK8UmAaxdG9jV1yRtVzGd": [ev]}}))
    monkeypatch.setattr(freezes, "TRON_DUMP_FILE", dump)
    freezes._MEMO.clear()
    assert freezes._history("tron")["TMzn3oX7caFKbJK8UmAaxdG9jV1yRtVzGd"][0]["type"] == "added"
    freezes._MEMO.clear()


def test_empty_settings_from_a_copied_env_example_mean_defaults():
    """Fresh clone: cp .env.example .env leaves HOUND_MAX_TRANSFERS= etc. as "" after python-dotenv.
    Importing the chain package must treat them as unset (it crashed at import before)."""
    import subprocess, sys, os as _o
    env = {**_o.environ, "HOUND_NO_DOTENV": "1", "HOUND_MAX_TRANSFERS": "", "HOUND_ETH_TRANSFER_SOURCES": "",
           "HOUND_TRACE_DIRS": "", "ETH_ARCHIVE_RPC_URL": "", "ETH_RPC_URLS": ""}
    code = ("import os, hound.chain as c; from hound.chain import eth; "
            "assert eth.MAX_TRANSFERS == 5000 and eth.ETH_ARCHIVE_RPC_URLS; "
            "assert 'HOUND_ETH_TRANSFER_SOURCES' not in os.environ and 'HOUND_TRACE_DIRS' not in os.environ; print('ok')")
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                       cwd=str(Path(__file__).resolve().parents[1]))
    assert r.stdout.strip() == "ok", r.stderr[-800:]
