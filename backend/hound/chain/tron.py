"""Tron adapter via TronGrid (works without a key at low volume; set TRONGRID_API_KEY for
~15 req/s). Same interface as eth.py. Addresses are base58 (T...), kept as-is.

Notes:
  - TronGrid's TRC-20 history has no block number or log index; "block" is None there.
  - No public Tron exchange-label dataset is wired in yet (Tronscan tags need a key), so Tron
    labels are OFAC-only for now. Busy exchange wallets still stop the trace via TooManyTransfers.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from decimal import Decimal
from typing import Any

from . import cache
from .eth import iso, parse_time
from . import net
from .net import ChainAPIError, TooManyTransfers, count_cache_hit, count_empty, request_json

log = logging.getLogger("hound.chain.tron")

CHAIN = "tron"
TRONGRID = os.environ.get("TRONGRID_URL", "https://api.trongrid.io")
USDT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
TOKENS = {"USDT": (USDT, 6)}
PAGE = 200
MAX_TRANSFERS = int(os.environ.get("HOUND_MAX_TRANSFERS", "5000"))
RECENT_TTL = 600.0
SETTLED_AFTER = 86400.0

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_ADDR = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")


# ---------------------------------------------------------------- addresses

def _b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = _B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + s


def _b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + _B58.index(c)
    full = n.to_bytes(25, "big")
    return full


def hex_to_base58(h: str) -> str:
    """0x-hex (20 bytes) or 41-prefixed hex -> T... address."""
    h = h.lower().removeprefix("0x")
    raw = bytes.fromhex("41" + h[-40:])
    chk = hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
    return _b58encode(raw + chk)


def base58_to_hex20(a: str) -> str:
    raw = _b58decode(norm(a))
    payload, chk = raw[:21], raw[21:]
    if hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != chk:
        raise ValueError(f"bad Tron address checksum: {a}")
    return payload[1:].hex()


def norm(address: str) -> str:
    a = (address or "").strip()
    if a.lower().startswith("0x") or (len(a) == 42 and a.startswith("41")):
        a = hex_to_base58(a)
    if not _ADDR.match(a):
        raise ValueError(f"not a Tron address: {address!r}")
    return a


# ---------------------------------------------------------------- HTTP

def _headers() -> dict:
    key = os.environ.get("TRONGRID_API_KEY")
    # keyless TronGrid allows 1 request/s (and suspends you for seconds if you go faster)
    net.MIN_INTERVAL["api.trongrid.io"] = 0.07 if key else 1.05
    return {"TRON-PRO-API-KEY": key} if key else {}


def _retry_reason(body: Any) -> str | None:
    if isinstance(body, dict) and body.get("success") is False:
        err = str(body.get("error", ""))
        if "limit" in err.lower() or "frequency" in err.lower():
            return f"trongrid throttled: {err[:200]}"
    return None


def _get(path: str, params: dict, ttl: Any) -> dict:
    def fetch():
        body = request_json("GET", f"{TRONGRID}{path}", params=params, headers=_headers(), retry_reason=_retry_reason)
        if not isinstance(body, dict) or body.get("success") is False:
            raise ChainAPIError(f"trongrid {path} {params}: {str(body)[:300]}")
        return body
    return cache.cached("tron", {"path": path, **params}, fetch=fetch, ttl=ttl, on_hit=count_cache_hit,
                        is_empty=lambda b: b.get("data") == [])


def _post(path: str, payload: dict, ttl: Any) -> dict:
    def fetch():
        body = request_json("POST", f"{TRONGRID}{path}", json_body=payload, headers=_headers(),
                            retry_reason=_retry_reason)
        if not isinstance(body, dict):
            raise ChainAPIError(f"trongrid {path}: {str(body)[:300]}")
        return body
    return cache.cached("tron", {"path": path, **payload}, fetch=fetch, ttl=ttl, on_hit=count_cache_hit)


def constant_call(contract: str, selector: str, param_hex: str, ttl: Any = 300) -> str:
    body = _post("/wallet/triggerconstantcontract", {
        "owner_address": contract, "contract_address": contract, "function_selector": selector,
        "parameter": param_hex, "visible": True}, ttl=ttl)
    res = body.get("constant_result")
    if not res or not (body.get("result") or {}).get("result", True):
        raise ChainAPIError(f"tron call {selector} on {contract} failed: {str(body)[:300]}")
    return res[0]


# ---------------------------------------------------------------- transfers

def _resolve(token: str | None) -> str | None:
    if token is None:
        return None
    if token.upper() in TOKENS:
        return TOKENS[token.upper()][0]
    if token.upper() == "TRX":
        raise ValueError("native TRX transfers are not supported yet; use token='USDT'")
    return norm(token)


def get_transfers(address: str, token: str | None = None, before: str | None = None,
                  after: str | None = None) -> list[dict]:
    """TRC-20 transfers in and out of `address`, oldest first. token: "USDT" | contract | None (all TRC-20)."""
    address = norm(address)
    contract = _resolve(token)
    params: dict[str, Any] = {"limit": PAGE, "only_confirmed": "true", "order_by": "block_timestamp,asc"}
    if contract:
        params["contract_address"] = contract
    if after:
        params["min_timestamp"] = parse_time(after) * 1000
    if before:
        params["max_timestamp"] = parse_time(before) * 1000 + 999
    bounded_old = before is not None and parse_time(before) < time.time() - SETTLED_AFTER

    def ttl(body):
        rows = body.get("data") or []
        if bounded_old or (len(rows) == PAGE and rows[-1]["block_timestamp"] / 1000 < time.time() - SETTLED_AFTER):
            return None
        return RECENT_TTL

    out: list[dict] = []
    path = f"/v1/accounts/{address}/transactions/trc20"
    page_params = dict(params)
    while True:
        body = _get(path, page_params, ttl)
        rows = body.get("data") or []
        for r in rows:
            ti = r.get("token_info") or {}
            dec = int(ti.get("decimals") or 0)
            raw = int(r.get("value") or 0)
            out.append({
                "chain": CHAIN, "tx_hash": r["transaction_id"], "from": r["from"], "to": r["to"],
                "token": ti.get("symbol") or "?", "amount": float(Decimal(raw) / Decimal(10) ** dec),
                "time": iso(r["block_timestamp"] // 1000), "block": None,
                "log_index": None, "amount_raw": str(raw), "decimals": dec, "contract": ti.get("address"),
                "type": r.get("type"),
            })
        if len(out) > MAX_TRANSFERS:
            raise TooManyTransfers(address, len(out), MAX_TRANSFERS)
        fp = (body.get("meta") or {}).get("fingerprint")
        if not fp or len(rows) < PAGE:
            break
        page_params = {**params, "fingerprint": fp}
    if not out:
        count_empty()
        log.warning("EMPTY transfer list for %s token=%s after=%s before=%s", address, token, after, before)
    return out


def get_balance(address: str, token: str = "USDT") -> float:
    address = norm(address)
    contract = _resolve(token)
    if contract is None:
        raise ValueError("get_balance needs a token")
    dec = TOKENS.get(token.upper(), (None, None))[1]
    if dec is None:
        dec = int(constant_call(contract, "decimals()", "", ttl=None), 16)
    res = constant_call(contract, "balanceOf(address)", base58_to_hex20(address).rjust(64, "0"), ttl=120)
    return float(Decimal(int(res, 16)) / Decimal(10) ** dec)


# ---------------------------------------------------------------- freezes

def is_blacklisted(address: str) -> bool:
    res = constant_call(USDT, "isBlackListed(address)", base58_to_hex20(address).rjust(64, "0"), ttl=300)
    return int(res, 16) != 0


def _events(name: str) -> list[dict]:
    path = f"/v1/contracts/{USDT}/events"
    params: dict[str, Any] = {"event_name": name, "limit": PAGE, "order_by": "block_timestamp,asc",
                              "only_confirmed": "true"}

    def ttl(body):
        rows = body.get("data") or []
        if len(rows) == PAGE and rows[-1]["block_timestamp"] / 1000 < time.time() - SETTLED_AFTER:
            return None
        return RECENT_TTL

    out = []
    page = dict(params)
    while True:
        body = _get(path, page, ttl)
        rows = body.get("data") or []
        out.extend(rows)
        fp = (body.get("meta") or {}).get("fingerprint")
        if not fp or len(rows) < PAGE:
            return out
        page = {**params, "fingerprint": fp}


def blacklist_history() -> dict[str, list[dict]]:
    """address -> [{"type": added|removed|destroyed, "block", "time", "tx", "log_index", ...}]"""
    hist: dict[str, list[dict]] = {}
    for kind, name in (("added", "AddedBlackList"), ("removed", "RemovedBlackList"),
                       ("destroyed", "DestroyedBlackFunds")):
        for r in _events(name):
            res = r.get("result") or {}
            user = res.get("_user") or res.get("_blackListedUser") or res.get("0")
            if not user:
                continue
            ev = {"type": kind, "block": r.get("block_number"), "time": iso(r["block_timestamp"] // 1000),
                  "tx": r.get("transaction_id"), "log_index": r.get("event_index", 0)}
            if kind == "destroyed":
                bal = res.get("_balance") or res.get("1")
                if bal is not None:
                    ev["amount"] = float(Decimal(int(bal)) / Decimal(10) ** 6)
            hist.setdefault(hex_to_base58(user), []).append(ev)
    for evs in hist.values():
        evs.sort(key=lambda e: (e["block"] or 0, e["log_index"] or 0))
    return hist
