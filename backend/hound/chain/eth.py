"""Ethereum adapter.

Sources (all responses disk-cached), tried in order:
  ERC-20 transfers  1. eth_getLogs on public RPCs that allow full-range queries filtered by the
                       indexed from/to topic (Tenderly gateway, MEV Blocker): 2 calls per address
                    2. Blockscout v2 REST (no key, ~180 req/min, sometimes 503s)
                    3. Etherscan V2 (needs ETHERSCAN_API_KEY)
                    4. Blockscout v1 (no key, but only ~10 requests per 30 min)
  ETH transfers     Etherscan V2 -> Blockscout v1 (txlist; logs don't cover native ETH)
  calls / balances  public JSON-RPC (ETH_RPC_URLS)
  logs              public RPC -> Etherscan -> Blockscout v1
Override the transfer order with HOUND_ETH_TRANSFER_SOURCES=rpc,blockscout_v2,etherscan,blockscout.
Amounts are returned in whole token units; times as ISO 8601 UTC.
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from . import cache
from .net import ChainAPIError, TooManyTransfers, count_cache_hit, count_empty, request_json, safe_url

log = logging.getLogger("hound.chain.eth")

CHAIN = "ethereum"
BLOCKSCOUT = os.environ.get("BLOCKSCOUT_URL", "https://eth.blockscout.com")
ETHERSCAN_API = "https://api.etherscan.io/v2/api"
ETH_RPC_URLS = [u.strip() for u in os.environ.get(
    "ETH_RPC_URLS",
    "https://ethereum-rpc.publicnode.com,https://mainnet.gateway.tenderly.co,https://rpc.mevblocker.io",
).split(",") if u.strip()]
# RPCs that accept full-history eth_getLogs (no archive token, no small range cap)
ETH_LOGS_RPC_URLS = [u.strip() for u in os.environ.get(
    "ETH_LOGS_RPC_URLS", "https://mainnet.gateway.tenderly.co,https://rpc.mevblocker.io",
).split(",") if u.strip()]
# Archive RPC for state at a past block (balances in a replay). Tenderly's public gateway
# answers past-block eth_call; set ETH_ARCHIVE_RPC_URL to an Alchemy/Infura URL for reliability.
ETH_ARCHIVE_RPC_URLS = [u.strip() for u in os.environ.get(
    "ETH_ARCHIVE_RPC_URL", "https://mainnet.gateway.tenderly.co,https://rpc.mevblocker.io").split(",") if u.strip()]
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
# Blocks older than this many are "settled": log queries ending there are cached forever.
SETTLE_BLOCKS = 7200  # ~1 day
SETTLE_ROUND = 50000  # round the settled boundary so its cache key stays stable for ~a week

USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
USDT_DEPLOY_BLOCK = 4634748
TOKENS = {"USDT": (USDT, 6)}  # symbol -> (contract, decimals)

V1_PAGE = 1000
V1_PAGES_PER_WINDOW = 10  # explorers refuse page * offset > 10,000
# Above this many transfers we stop and raise TooManyTransfers: the address is an
# exchange or a service, and a fraud trace should stop there, not download it all.
MAX_TRANSFERS = int(os.environ.get("HOUND_MAX_TRANSFERS", "5000"))

RECENT_TTL = 600.0  # data that can still change: 10 min
SETTLED_AFTER = 86400.0  # data older than a day is final

_ADDR = re.compile(r"^0x[0-9a-f]{40}$")
_EMPTY_MESSAGES = ("no transactions found", "no token transfers found", "no records found", "no logs found")


# ---------------------------------------------------------------- helpers

def norm(address: str) -> str:
    a = (address or "").strip().lower()
    if not _ADDR.match(a):
        raise ValueError(f"not an Ethereum address: {address!r}")
    return a


def iso(ts: int | float) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(t: str | int | float | datetime) -> int:
    """ISO 8601 string (or unix seconds, or datetime) -> unix seconds."""
    if isinstance(t, (int, float)):
        return int(t)
    dt = t if isinstance(t, datetime) else datetime.fromisoformat(t.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _amount(raw: int, decimals: int) -> float:
    return float(Decimal(raw) / (Decimal(10) ** decimals))


def _resolve_token(token: str | None) -> tuple[str, str | None, int | None]:
    """-> (kind "erc20" | "eth", contract or None, decimals or None)"""
    if token is None:
        return "erc20", None, None
    t = token.strip()
    if t.upper() == "ETH":
        return "eth", None, 18
    if t.upper() in TOKENS:
        c, d = TOKENS[t.upper()]
        return "erc20", c, d
    return "erc20", norm(t), None


# ---------------------------------------------------------------- Etherscan-style (v1) calls

def _v1_retry_reason(body: Any) -> str | None:
    if not isinstance(body, dict):
        return f"unexpected body type {type(body).__name__}"
    if body.get("status") == "0":
        text = f"{body.get('message', '')} {body.get('result', '')}".lower()
        if "rate limit" in text or "too many" in text or "timeout" in text or "try again" in text:
            return f"explorer throttled/timeout: {body.get('message')} {body.get('result')}"
    return None


def _is_empty_v1(body: Any) -> bool:
    return isinstance(body, dict) and isinstance(body.get("result"), list) and not body["result"]


def _v1_once(params: dict, source: str) -> dict:
    if source == "etherscan":
        url, full = ETHERSCAN_API, {"chainid": 1, **params, "apikey": os.environ.get("ETHERSCAN_API_KEY")}
    else:
        url, full = f"{BLOCKSCOUT}/api", dict(params)
        if os.environ.get("BLOCKSCOUT_API_KEY"):
            full["apikey"] = os.environ["BLOCKSCOUT_API_KEY"]
    body = request_json("GET", url, params=full, retry_reason=_v1_retry_reason)
    if body.get("status") == "1" or body.get("message") == "OK":
        return body
    msg = str(body.get("message", "")).lower()
    if _is_empty_v1(body) or any(m in msg for m in _EMPTY_MESSAGES):
        body["result"] = body.get("result") or []
        return body
    raise ChainAPIError(f"{source} error for {params}: {body.get('message')} / {str(body.get('result'))[:300]}")


def _v1_fetch(params: dict, source: str) -> dict:
    body = _v1_once(params, source)
    if _is_empty_v1(body):
        time.sleep(1.5)  # retry an empty answer once before believing it (the kill test's silent zero)
        body = _v1_once(params, source)
        if not _is_empty_v1(body):
            log.warning("EMPTY result became non-empty on retry (%s %s)", source, params)
    return body


def v1_sources() -> list[str]:
    return (["etherscan"] if os.environ.get("ETHERSCAN_API_KEY") else []) + ["blockscout"]


def explorer(params: dict, ttl: Any = RECENT_TTL, sources: list[str] | None = None) -> dict:
    """Etherscan-compatible call, trying each source in order until one works."""
    sources = sources or v1_sources()
    errors = []
    for source in sources:
        try:
            body = cache.cached("eth_v1", {"source": source, **params},
                                fetch=lambda s=source: _v1_fetch(params, s),
                                ttl=ttl, is_empty=_is_empty_v1, on_hit=count_cache_hit)
        except cache.CacheMiss:
            continue  # offline: maybe another source was cached
        except ChainAPIError as e:
            errors.append(f"{source}: {e}")
            log.warning("%s failed: %s", source, e)
            continue
        if _is_empty_v1(body):
            count_empty()
            log.warning("EMPTY result from %s for %s", source, params)
        return body
    if not errors:
        raise cache.CacheMiss(f"HOUND_OFFLINE=1 and nothing cached for {params}")
    raise ChainAPIError(f"every source failed for {params}: {' | '.join(errors)}")


# ---------------------------------------------------------------- JSON-RPC

TOO_BIG_MARKER = "__hound_range_too_big__"


class RangeTooBig(ChainAPIError):
    """An RPC refused a log query for its size; split the block range and retry."""


_SIZE_ERRORS = ("more than", "too many", "exceed", "limit", "range", "too large", "response size", "10000")


_NULL_IS_MISSING = ("eth_getTransactionByHash", "eth_getTransactionReceipt", "eth_getBlockByNumber")


def _rpc_once(url: str, method: str, params: list) -> Any:
    body = request_json("POST", url, json_body={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                        retries=3)
    if isinstance(body, dict) and "error" in body:
        msg = str(body["error"])
        if method == "eth_getLogs" and any(s in msg.lower() for s in _SIZE_ERRORS):
            raise RangeTooBig(f"{safe_url(url)}: {msg[:200]}")
        raise ChainAPIError(f"{safe_url(url)} {method}: {msg[:300]}")
    if not isinstance(body, dict) or "result" not in body:
        raise ChainAPIError(f"{safe_url(url)} {method}: malformed response {str(body)[:200]}")
    if body["result"] is None and method in _NULL_IS_MISSING:
        # pruned nodes answer null for old data: try the next RPC instead of believing it
        raise ChainAPIError(f"{safe_url(url)} {method}: null result (pruned node?)")
    return body["result"]


def rpc(method: str, params: list, ttl: Any = RECENT_TTL, urls: list[str] | None = None) -> Any:
    """JSON-RPC with fail-over across `urls`; cached by (method, params)."""
    urls = urls or ETH_RPC_URLS

    def fetch():
        errors = []
        size_errors = 0
        for url in urls:
            try:
                return _rpc_once(url, method, params)
            except RangeTooBig as e:
                size_errors += 1
                errors.append(str(e))
            except ChainAPIError as e:
                errors.append(str(e))
                log.warning("rpc %s %s failed: %s", safe_url(url), method, e)
        if size_errors and size_errors == len(errors):
            # remembered, so cached / readonly replays split the range the same way
            return {TOO_BIG_MARKER: " | ".join(errors)[:300]}
        raise ChainAPIError(f"every RPC failed for {method}: {' | '.join(errors)}")

    parts = {"method": method, "params": params}
    if method in _NULL_IS_MISSING:
        entry = cache.read("eth_rpc", parts)
        if entry is not None and entry.get("value") is None and not cache.offline():
            cache.write("eth_rpc", parts, fetch())  # a cached null from a pruned node: refetch
    out = cache.cached("eth_rpc", parts, fetch=fetch, ttl=ttl, on_hit=count_cache_hit, is_empty=lambda r: r == [])
    if isinstance(out, dict) and TOO_BIG_MARKER in out:
        raise RangeTooBig(out[TOO_BIG_MARKER])
    return out


def _settled_block(head: int) -> int:
    return max(0, (head - SETTLE_BLOCKS) // SETTLE_ROUND * SETTLE_ROUND)


def rpc_logs(flt: dict, from_block: int, to_block: int | None = None, cap: int | None = None,
             on_cap: Callable[[int], Exception] | None = None) -> list[dict]:
    """eth_getLogs over [from_block, to_block or latest], cached, split in half whenever an RPC
    says the query is too big. The settled part (older than ~1 day) is cached forever."""
    head = latest_block()
    end = head if to_block is None else min(to_block, head)
    settled = _settled_block(head)
    segments = []
    if from_block <= min(end, settled):
        segments.append((from_block, min(end, settled), True))
    if end > settled:
        segments.append((max(from_block, settled + 1), end, False))

    out: list[dict] = []

    def run(lo: int, hi: int, final: bool, latest_tag: bool):
        params = [{**flt, "fromBlock": hex(lo), "toBlock": "latest" if latest_tag else hex(hi)}]
        try:
            rows = rpc("eth_getLogs", params, ttl=None if final else RECENT_TTL, urls=ETH_LOGS_RPC_URLS)
        except RangeTooBig:
            if hi - lo < 1:
                raise ChainAPIError(f"logs for a single block {lo} too big: {flt}")
            mid = (lo + hi) // 2
            run(lo, mid, final or mid <= settled, False)
            run(mid + 1, hi, final, latest_tag)
            return
        out.extend(rows)
        if cap is not None and len(out) > cap:
            raise on_cap(len(out)) if on_cap else ChainAPIError(f"more than {cap} logs for {flt}")

    for lo, hi, final in segments:
        run(lo, hi, final, latest_tag=(not final and to_block is None))
    return out


def _topic_addr(address: str) -> str:
    return "0x" + norm(address)[2:].rjust(64, "0")


def eth_call(to: str, data: str, ttl: Any = 300) -> str:
    return rpc("eth_call", [{"to": norm(to), "data": data}, "latest"], ttl=ttl)


def latest_block() -> int:
    if cache.offline():
        # offline: the last head we saw (so settled-range cache keys still line up)
        entry = cache.read("eth_rpc", {"method": "eth_blockNumber", "params": []})
        if entry:
            return int(entry["value"], 16)
    return int(rpc("eth_blockNumber", [], ttl=12), 16)


def block_time(block: int) -> int:
    b = rpc("eth_getBlockByNumber", [hex(block), False], ttl=None)
    if not b:
        raise ChainAPIError(f"no block {block}")
    return int(b["timestamp"], 16)


MERGE_BLOCK, MERGE_TS = 15537394, 1663224179  # first proof-of-stake block: 12 s slots after this


def block_at(t: str | int, closest: str = "before") -> int:
    """Block number at time t (ISO or unix) via RPC block timestamps (interpolation, then
    binary search; every block lookup is cached forever).
    closest="before": last block with timestamp <= t. "after": first block with timestamp >= t."""
    ts = parse_time(t)
    head = latest_block()
    if ts >= block_time(head):
        return head
    if ts <= block_time(1):
        return 0 if closest == "before" else 1
    # bracket [lo, hi] with time(lo) <= ts < time(hi)
    guess = MERGE_BLOCK + (ts - MERGE_TS) // 12 if ts >= MERGE_TS else int(ts - 1438269988) // 14
    guess = min(max(guess, 1), head)
    step = 64
    lo, hi = guess, guess
    while lo > 1 and block_time(lo) > ts:
        lo = max(1, lo - step)
        step *= 4
    step = 64
    while hi < head and block_time(hi) <= ts:
        hi = min(head, hi + step)
        step *= 4
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if block_time(mid) <= ts:
            lo = mid
        else:
            hi = mid
    if closest == "before":
        return lo
    return lo if block_time(lo) == ts else hi


# ---------------------------------------------------------------- transfers

def get_transfers(address: str, token: str | None = None, before: str | None = None,
                  after: str | None = None) -> list[dict]:
    """Every transfer in or out of `address`, oldest first.

    token: "USDT" | "ETH" | a token contract | None (all ERC-20 tokens, not ETH).
    before / after: ISO 8601 UTC bounds (inclusive).
    Raises TooManyTransfers above HOUND_MAX_TRANSFERS, ChainAPIError if every source fails.
    """
    address = norm(address)
    kind, contract, _ = _resolve_token(token)
    lo = parse_time(after) if after else None
    hi = parse_time(before) if before else None

    errors = []
    runners: dict[str, Callable[[], list[dict]]] = {
        "rpc": lambda: _transfers_rpc(address, contract, lo, hi),
        "blockscout_v2": lambda: _transfers_v2(address, contract, lo, hi),
        "etherscan": lambda: _transfers_v1(address, kind, contract, lo, hi, "etherscan"),
        "blockscout": lambda: _transfers_v1(address, kind, contract, lo, hi, "blockscout"),
    }
    order = [s.strip() for s in os.environ.get("HOUND_ETH_TRANSFER_SOURCES",
                                               "rpc,blockscout_v2,etherscan,blockscout").split(",")]
    if kind == "eth":
        order = [s for s in order if s in ("etherscan", "blockscout")]  # native ETH isn't in logs
    if not os.environ.get("ETHERSCAN_API_KEY"):
        order = [s for s in order if s != "etherscan"]
    attempts = [(s, runners[s]) for s in order if s in runners]

    for name, run in attempts:
        try:
            out = run()
        except (TooManyTransfers, cache.CacheMiss):
            raise
        except ChainAPIError as e:
            errors.append(f"{name}: {e}")
            log.warning("transfers via %s failed for %s: %s", name, address, e)
            continue
        out = [t for t in out if (lo is None or parse_time(t["time"]) >= lo) and
               (hi is None or parse_time(t["time"]) <= hi)]
        out.sort(key=lambda t: (t["block"], t.get("log_index") if t.get("log_index") is not None else -1))
        if not out:
            count_empty()
            log.warning("EMPTY transfer list for %s token=%s after=%s before=%s (source %s)",
                        address, token, after, before, name)
        return out
    raise ChainAPIError(f"could not get transfers for {address}: {' | '.join(errors)}")


_DECIMALS_CACHE: dict[str, tuple[str, int]] = {USDT: ("USDT", 6)}


def _token_meta(contract: str) -> tuple[str, int]:
    """(symbol, decimals) for an ERC-20 contract, via eth_call (cached forever)."""
    if contract in _DECIMALS_CACHE:
        return _DECIMALS_CACHE[contract]
    try:
        dec = int(eth_call(contract, "0x313ce567", ttl=None), 16)  # decimals()
    except (ChainAPIError, ValueError) as e:
        raise ChainAPIError(f"can't read decimals() of token {contract}: {e}") from e
    sym = "?"
    try:
        raw = eth_call(contract, "0x95d89b41", ttl=None)  # symbol()
        b = bytes.fromhex(raw[2:])
        if len(b) >= 96:
            n = int.from_bytes(b[32:64], "big")
            sym = b[64:64 + n].decode("utf-8", "replace")
        elif len(b) == 32:
            sym = b.rstrip(b"\0").decode("utf-8", "replace")
    except (ChainAPIError, ValueError):
        pass
    _DECIMALS_CACHE[contract] = (sym, dec)
    return sym, dec


def _transfers_rpc(address: str, contract: str | None, lo: int | None, hi: int | None) -> list[dict]:
    """ERC-20 Transfer logs where `address` is the indexed sender or receiver.

    Fetches the full history (2 cached calls) and lets the caller filter by time; only if
    that's over the cap and a time window was asked for, retries bounded to the window."""
    start = USDT_DEPLOY_BLOCK if contract == USDT else 0
    try:
        return _transfers_rpc_range(address, contract, start, None)
    except TooManyTransfers:
        if lo is None and hi is None:
            raise
        a = block_at(lo, "after") // SETTLE_ROUND * SETTLE_ROUND if lo else start
        b = block_at(hi, "before") if hi else None
        log.info("%s is busy; retrying transfers bounded to blocks %s..%s", address, a, b)
        return _transfers_rpc_range(address, contract, a, b)


def _transfers_rpc_range(address: str, contract: str | None, from_block: int, to_block: int | None) -> list[dict]:
    me = _topic_addr(address)
    base = {"topics": None}
    if contract:
        base["address"] = contract
    rows: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for topics in ([TRANSFER_TOPIC, me], [TRANSFER_TOPIC, None, me]):
        flt = {**base, "topics": topics}
        got = rpc_logs(flt, from_block, to_block, cap=MAX_TRANSFERS,
                       on_cap=lambda n: TooManyTransfers(address, n, MAX_TRANSFERS))
        for r in got:
            k = (r["transactionHash"].lower(), int(r["logIndex"], 16))
            if k not in seen:  # a self-transfer shows up in both queries
                seen.add(k)
                rows.append(r)
        if len(rows) > MAX_TRANSFERS:
            raise TooManyTransfers(address, len(rows), MAX_TRANSFERS)
    out = []
    for r in rows:
        if len(r["topics"]) != 3:
            continue  # ERC-721 Transfer has 4 topics; malformed tokens have fewer
        c = r["address"].lower()
        sym, dec = _token_meta(c)
        raw = int(r["data"], 16) if r.get("data") not in (None, "0x") else 0
        bt = r.get("blockTimestamp")
        ts = int(bt, 16) if bt else block_time(int(r["blockNumber"], 16))
        out.append({
            "chain": CHAIN,
            "tx_hash": r["transactionHash"].lower(),
            "from": "0x" + r["topics"][1][-40:].lower(),
            "to": "0x" + r["topics"][2][-40:].lower(),
            "token": sym,
            "amount": _amount(raw, dec),
            "time": iso(ts),
            "block": int(r["blockNumber"], 16),
            "log_index": int(r["logIndex"], 16),
            "tx_index": int(r["transactionIndex"], 16) if r.get("transactionIndex") else None,
            "amount_raw": str(raw),
            "decimals": dec,
            "contract": c,
        })
    return out


def _v2_get(path: str, params: dict, ttl: Any) -> dict:
    url = f"{BLOCKSCOUT}{path}"

    def fetch():
        return request_json("GET", url, params=params or None)

    return cache.cached("eth_v2", {"path": path, **params}, fetch=fetch, ttl=ttl, on_hit=count_cache_hit,
                        is_empty=lambda b: isinstance(b, dict) and b.get("items") == [])


def _transfers_v2(address: str, contract: str | None, lo: int | None, hi: int | None) -> list[dict]:
    """Blockscout v2 lists newest first, 50 per page, with keyset cursors."""
    path = f"/api/v2/addresses/{address}/token-transfers"
    params: dict[str, Any] = {"type": "ERC-20"}
    if contract:
        params["token"] = contract
    out: list[dict] = []
    first = True
    while True:
        def ttl(body, first_page=first):
            items = body.get("items") or []
            if not first_page and items and parse_time(items[0]["timestamp"]) < time.time() - SETTLED_AFTER:
                return None  # cursor page of old rows: final
            return RECENT_TTL

        body = _v2_get(path, params, ttl)
        items = body.get("items")
        if items is None:
            raise ChainAPIError(f"blockscout v2 bad response for {address}: {str(body)[:300]}")
        if first and not items:
            # retry an empty first page once, bypassing the cache
            time.sleep(1.5)
            body = request_json("GET", f"{BLOCKSCOUT}{path}", params=params)
            items = body.get("items") or []
            if items:
                log.warning("EMPTY v2 page became non-empty on retry for %s", address)
                cache.write("eth_v2", {"path": path, **params}, body)
        oldest_ts = None
        for it in items:
            t = _v2_item(it)
            if t is None:
                continue
            oldest_ts = parse_time(t["time"])
            out.append(t)
            if len(out) > MAX_TRANSFERS:
                raise TooManyTransfers(address, len(out), MAX_TRANSFERS)
        nxt = body.get("next_page_params")
        if not nxt:
            return out
        if lo is not None and oldest_ts is not None and oldest_ts < lo:
            return out  # newest-first: everything after this is older than `after`
        params = {"type": "ERC-20", **({"token": contract} if contract else {}), **nxt}
        first = False


def _v2_item(it: dict) -> dict | None:
    total = it.get("total") or {}
    if total.get("value") is None:
        return None  # NFTs etc.
    decimals = int(total.get("decimals") or (it.get("token") or {}).get("decimals") or 0)
    raw = int(total["value"])
    token = it.get("token") or {}
    frm = ((it.get("from") or {}).get("hash") or "").lower()
    to = ((it.get("to") or {}).get("hash") or "").lower()
    return {
        "chain": CHAIN,
        "tx_hash": it["transaction_hash"].lower(),
        "from": frm,
        "to": to,
        "token": token.get("symbol") or "?",
        "amount": _amount(raw, decimals),
        "time": iso(parse_time(it["timestamp"])),
        "block": int(it["block_number"]),
        # extras beyond the contract (safe to ignore)
        "log_index": it.get("log_index"),
        "amount_raw": str(raw),
        "decimals": decimals,
        "contract": (token.get("address_hash") or token.get("address") or "").lower() or None,
    }


def _transfers_v1(address: str, kind: str, contract: str | None, lo: int | None, hi: int | None,
                  source: str) -> list[dict]:
    action = "txlist" if kind == "eth" else "tokentx"
    start = block_at(lo, "after") if lo else 0
    end = block_at(hi, "before") if hi else 99999999
    end_old = hi is not None and hi < time.time() - SETTLED_AFTER

    def ttl(body):
        rows = body.get("result") or []
        if end_old or (len(rows) == V1_PAGE and int(rows[-1].get("timeStamp", 0)) < time.time() - SETTLED_AFTER):
            return None
        return RECENT_TTL

    rows_out: list[dict] = []
    window_start = start
    while True:
        window: list[dict] = []
        for page in range(1, V1_PAGES_PER_WINDOW + 1):
            params = {"module": "account", "action": action, "address": address, "startblock": window_start,
                      "endblock": end, "page": page, "offset": V1_PAGE, "sort": "asc"}
            if contract:
                params["contractaddress"] = contract
            rows = explorer(params, ttl=ttl, sources=[source])["result"]
            window.extend(rows)
            if len(rows_out) + len(window) > MAX_TRANSFERS:
                raise TooManyTransfers(address, len(rows_out) + len(window), MAX_TRANSFERS)
            if len(rows) < V1_PAGE:
                rows_out.extend(window)
                return [t for t in (_v1_row(r, action) for r in rows_out) if t]
        last_block = int(window[-1]["blockNumber"])
        if last_block == window_start:
            raise ChainAPIError(f"{address}: >{V1_PAGE * V1_PAGES_PER_WINDOW} transfers in block {last_block}")
        # restart at the last block and drop its rows here (they're re-fetched whole)
        rows_out.extend(r for r in window if int(r["blockNumber"]) < last_block)
        window_start = last_block


def _v1_row(row: dict, action: str) -> dict | None:
    raw = int(row.get("value") or 0)
    if action == "txlist":
        if row.get("isError") not in (None, "0") or row.get("txreceipt_status") == "0" or raw == 0:
            return None
        symbol, decimals, contract = "ETH", 18, None
    else:
        symbol = row.get("tokenSymbol") or "?"
        decimals = int(row.get("tokenDecimal") or 0)
        contract = (row.get("contractAddress") or "").lower() or None
    li = row.get("logIndex")
    return {
        "chain": CHAIN,
        "tx_hash": row["hash"].lower(),
        "from": (row.get("from") or "").lower(),
        "to": (row.get("to") or "").lower(),
        "token": symbol,
        "amount": _amount(raw, decimals),
        "time": iso(int(row["timeStamp"])),
        "block": int(row["blockNumber"]),
        "log_index": int(li, 16) if isinstance(li, str) and li.startswith("0x") else (int(li) if li else None),
        "tx_index": int(row["transactionIndex"]) if row.get("transactionIndex") not in (None, "") else None,
        "amount_raw": str(raw),
        "decimals": decimals,
        "contract": contract,
    }


# ---------------------------------------------------------------- balances

def _pad(address: str) -> str:
    return norm(address)[2:].rjust(64, "0")


def get_balance(address: str, token: str = "USDT", block: int | None = None) -> float:
    """Balance in whole units, read on-chain. block=None is latest; a block number reads the
    state at that block from an archive RPC (cached forever)."""
    address = norm(address)
    kind, contract, decimals = _resolve_token(token)
    tag = "latest" if block is None else hex(int(block))
    ttl = 120 if block is None else None
    urls = None if block is None else ETH_ARCHIVE_RPC_URLS
    if kind == "eth":
        return _amount(int(rpc("eth_getBalance", [address, tag], ttl=ttl, urls=urls), 16), 18)
    if contract is None:
        raise ValueError("get_balance needs a token (USDT, ETH or a contract)")
    if decimals is None:
        decimals = _token_meta(contract)[1]
    res = rpc("eth_call", [{"to": contract, "data": "0x70a08231" + _pad(address)}, tag], ttl=ttl, urls=urls)
    if not res or res == "0x":
        raise ChainAPIError(f"empty balanceOf result for {address} on {contract} at {tag}")
    return _amount(int(res, 16), decimals)


# ---------------------------------------------------------------- logs

def get_logs(contract: str, topic0: str, from_block: int, to_block: int | None = None) -> list[dict]:
    """All logs of `contract` with `topic0` in [from_block, to_block], oldest first.
    Public RPC first; explorer fallback pages by block (at most 1000 per call)."""
    contract = norm(contract)
    try:
        rows = rpc_logs({"address": contract, "topics": [topic0]}, from_block, to_block)
        rows.sort(key=lambda r: (int(r["blockNumber"], 16), int(r["logIndex"], 16)))
        return rows
    except cache.CacheMiss:
        raise
    except ChainAPIError as e:
        log.warning("rpc getLogs failed (%s); falling back to explorers", e)
    out: list[dict] = []
    seen: set[tuple[str, int]] = set()
    cur = from_block
    bounded_old = to_block is not None and to_block < latest_block() - 64
    while True:
        params = {"module": "logs", "action": "getLogs", "address": contract, "topic0": topic0,
                  "fromBlock": cur, "toBlock": to_block if to_block is not None else "latest"}

        def ttl(body):
            # a full page from a fixed start block can't change; neither can an old bounded range
            return None if bounded_old or len(body.get("result") or []) >= 1000 else RECENT_TTL

        rows = explorer(params, ttl=ttl)["result"]
        for r in rows:
            li = r.get("logIndex") or "0x0"
            k = (r["transactionHash"].lower(), int(li, 16) if str(li).startswith("0x") else int(li))
            if k not in seen:
                seen.add(k)
                out.append(r)
        if len(rows) < 1000:
            return out
        last = _hex_or_int(rows[-1]["blockNumber"])
        if last == cur:
            raise ChainAPIError(f"more than 1000 logs in block {last}; can't paginate")
        cur = last  # re-query from the last block; dedupe on (tx, logIndex)


def _hex_or_int(v: Any) -> int:
    s = str(v)
    return int(s, 16) if s.startswith("0x") else int(s)


# ---------------------------------------------------------------- native ETH txs

def get_native_txs(address: str, as_of: int | str | None = None, after: str | None = None) -> list[dict]:
    """Every successful transaction where `address` is sender or recipient, oldest first:
    {chain, tx_hash, tx_index, from, to, token: "ETH", kind: "native", amount_wei (str),
     gas_wei (str, fee paid), block, time}. Zero-value calls are kept (they pay gas);
    failed transactions are dropped (no ETH moves). Internal transfers are not included.
    as_of: inclusive cutoff block (int) or ISO time. after: ISO time.
    Sources: Blockscout v2 -> Etherscan txlist (keyed) -> Blockscout v1."""
    address = norm(address)
    lo = parse_time(after) if after else None
    hi_time = parse_time(as_of) if isinstance(as_of, str) else None
    hi_block = as_of if isinstance(as_of, int) else None
    errors = []
    sources = [("blockscout_v2", lambda: _native_v2(address, lo))]
    sources += [(s, lambda s=s: _native_v1(address, s)) for s in v1_sources()]
    for name, run in sources:
        try:
            rows = run()
        except (TooManyTransfers, cache.CacheMiss):
            raise
        except ChainAPIError as e:
            errors.append(f"{name}: {e}")
            log.warning("native txs via %s failed for %s: %s", name, address, e)
            continue
        out = [r for r in rows
               if (lo is None or parse_time(r["time"]) >= lo)
               and (hi_time is None or parse_time(r["time"]) <= hi_time)
               and (hi_block is None or r["block"] <= hi_block)]
        out.sort(key=lambda r: (r["block"], r["tx_index"] if r["tx_index"] is not None else -1))
        if not out:
            count_empty()
            log.warning("EMPTY native tx list for %s after=%s as_of=%s (source %s)", address, after, as_of, name)
        return out
    raise ChainAPIError(f"could not get native txs for {address}: {' | '.join(errors)}")


def _native_row(tx_hash, tx_index, frm, to, value, fee, block, ts) -> dict:
    return {"chain": CHAIN, "tx_hash": tx_hash.lower(), "tx_index": tx_index, "from": (frm or "").lower(),
            "to": (to or "").lower(), "token": "ETH", "kind": "native", "amount_wei": str(int(value or 0)),
            "gas_wei": str(int(fee or 0)), "block": int(block), "time": iso(ts)}


def _native_v2(address: str, lo: int | None) -> list[dict]:
    path = f"/api/v2/addresses/{address}/transactions"
    params: dict[str, Any] = {}
    out: list[dict] = []
    first = True
    while True:
        def ttl(body, first_page=first):
            items = body.get("items") or []
            if not first_page and items and parse_time(items[0]["timestamp"]) < time.time() - SETTLED_AFTER:
                return None
            return RECENT_TTL

        body = _v2_get(path, params, ttl)
        items = body.get("items")
        if items is None:
            raise ChainAPIError(f"blockscout v2 bad transactions response for {address}: {str(body)[:300]}")
        oldest = None
        for it in items:
            if it.get("status") not in ("ok", None) or it.get("result") not in ("success", None):
                continue  # failed tx: no value moved
            if it.get("block_number") is None:
                continue  # pending
            fee = (it.get("fee") or {}).get("value")
            ts = parse_time(it["timestamp"])
            oldest = ts
            out.append(_native_row(it["hash"], it.get("position"), (it.get("from") or {}).get("hash"),
                                   (it.get("to") or {}).get("hash"), it.get("value"), fee, it["block_number"], ts))
            if len(out) > MAX_TRANSFERS:
                raise TooManyTransfers(address, len(out), MAX_TRANSFERS)
        nxt = body.get("next_page_params")
        if not nxt or (lo is not None and oldest is not None and oldest < lo):
            return out
        params = dict(nxt)
        first = False


def _native_v1(address: str, source: str) -> list[dict]:
    rows = []
    start = 0
    while True:
        params = {"module": "account", "action": "txlist", "address": address, "startblock": start,
                  "endblock": 99999999, "page": 1, "offset": V1_PAGE, "sort": "asc"}
        page = explorer(params, ttl=RECENT_TTL, sources=[source])["result"]
        rows.extend(page)
        if len(rows) > MAX_TRANSFERS:
            raise TooManyTransfers(address, len(rows), MAX_TRANSFERS)
        if len(page) < V1_PAGE:
            break
        last = int(page[-1]["blockNumber"])
        if last == start:
            raise ChainAPIError(f"{address}: >{V1_PAGE} txs in block {last}")
        rows = [r for r in rows if int(r["blockNumber"]) < last]
        start = last
    out = []
    seen = set()
    for r in rows:
        if r.get("isError") not in (None, "0") or r.get("txreceipt_status") == "0":
            continue
        if r["hash"] in seen:
            continue
        seen.add(r["hash"])
        fee = int(r.get("gasUsed") or 0) * int(r.get("gasPrice") or 0)
        out.append(_native_row(r["hash"], int(r["transactionIndex"]) if r.get("transactionIndex") else None,
                               r.get("from"), r.get("to"), r.get("value"), fee, r["blockNumber"], int(r["timeStamp"])))
    return out


def is_contract(address: str) -> bool:
    """True if the address has contract code now (eth_getCode, cached forever)."""
    code = rpc("eth_getCode", [norm(address), "latest"], ttl=None)
    return bool(code) and code not in ("0x", "0x0")


# ---------------------------------------------------------------- victim sends from a tx hash

_TX_HASH = re.compile(r"^0x[0-9a-f]{64}$")


def tx_sends(tx_hash: str, to: str | None = None) -> list[dict]:
    """Case `sends` from one victim transaction: its native ETH value and every USDT Transfer the
    sender made in it, read from the tx + receipt (cached forever once mined).
    to: keep only sends to this address. Failed or pending txs raise ValueError."""
    h = (tx_hash or "").strip().lower()
    if not _TX_HASH.match(h):
        raise ValueError(f"not an Ethereum tx hash: {tx_hash!r}")
    urls = ETH_ARCHIVE_RPC_URLS + [u for u in ETH_RPC_URLS if u not in ETH_ARCHIVE_RPC_URLS]
    try:
        tx = rpc("eth_getTransactionByHash", [h], ttl=None, urls=urls)
        rc = rpc("eth_getTransactionReceipt", [h], ttl=None, urls=urls)
    except ChainAPIError as e:
        raise ValueError(f"tx {h} not found on any RPC (wrong chain, or not mined yet): {e}") from e
    if not tx.get("blockNumber"):
        raise ValueError(f"tx {h} is still pending")
    if int(rc.get("status", "0x0"), 16) != 1:
        raise ValueError(f"tx {h} failed on chain: no money moved")
    block = int(tx["blockNumber"], 16)
    when = iso(block_time(block))
    sender = tx["from"].lower()
    sends = []
    value = int(tx.get("value") or "0x0", 16)
    if value > 0 and tx.get("to"):
        sends.append({"chain": CHAIN, "tx_hash": h, "from": sender, "to": tx["to"].lower(), "token": "ETH",
                      "amount": _amount(value, 18), "time": when})
    for lg in rc.get("logs", []):
        t = lg.get("topics") or []
        if lg.get("address", "").lower() != USDT or len(t) != 3 or t[0] != TRANSFER_TOPIC:
            continue
        frm, dst = "0x" + t[1][-40:].lower(), "0x" + t[2][-40:].lower()
        raw = int(lg.get("data") or "0x0", 16)
        if frm == sender and raw > 0 and frm != dst:
            sends.append({"chain": CHAIN, "tx_hash": h, "from": frm, "to": dst, "token": "USDT",
                          "amount": _amount(raw, 6), "time": when})
    if to:
        sends = [s for s in sends if s["to"] == norm(to)]
    return sends
