"""Tether (USDT) freezes: public AddedBlackList / RemovedBlackList / DestroyedBlackFunds events.

freeze_status() asks the USDT contract directly (isBlackListed) so "is it frozen right now"
is always the on-chain truth, then uses the event history for when and by which tx.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from . import eth
from .net import ChainAPIError

log = logging.getLogger("hound.chain.freezes")

TOPIC_ADDED = "0x42e160154868087d6bfdc0ca23d96a1c1cfa32f1b72ba9ba27b69b98a0d819dc"  # AddedBlackList(address)
TOPIC_REMOVED = "0xd7e9ec6e6ecd65492dce6bf513cd6867560d49544421d0783ddf06e76c24470c"  # RemovedBlackList(address)
TOPIC_DESTROYED = "0x61e6e66b0d6339b2980aecc6ccc0039736791f0ccde9ed512e789a7fbdd698c6"  # DestroyedBlackFunds(address,uint256)
SEL_IS_BLACKLISTED = "0xe47d6060"  # isBlackListed(address)


def _eth_events(topic: str) -> list[dict]:
    rows = eth.get_logs(eth.USDT, topic, eth.USDT_DEPLOY_BLOCK)
    out = []
    for r in rows:
        data = r.get("data") or "0x"
        if len(data) < 66:
            log.warning("malformed USDT blacklist log %s", r.get("transactionHash"))
            continue
        bt = r.get("blockTimestamp") or r.get("timeStamp")
        block = int(r["blockNumber"], 16)
        ts = int(bt, 16) if bt else eth.block_time(block)
        ev = {
            "address": "0x" + data[26:66].lower(),
            "block": block,
            "time": eth.iso(ts),
            "tx": r["transactionHash"].lower(),
            "log_index": int(r.get("logIndex") or "0x0", 16),
        }
        if topic == TOPIC_DESTROYED and len(data) >= 130:
            ev["amount"] = eth._amount(int(data[66:130], 16), 6)
        out.append(ev)
    return out


_MEMO: dict[str, tuple[float, dict]] = {}
MEMO_TTL = 60.0


def _history(chain: str) -> dict[str, list[dict]]:
    """address -> chronological list of {"type": added|removed|destroyed, ...} (memoised 60 s)."""
    hit = _MEMO.get(chain)
    if hit and time.time() - hit[0] < MEMO_TTL:
        return hit[1]
    hist = _load_history(chain)
    _MEMO[chain] = (time.time(), hist)
    return hist


def _load_history(chain: str) -> dict[str, list[dict]]:
    if chain != "ethereum":
        from . import tron
        return tron.blacklist_history()
    hist: dict[str, list[dict]] = {}
    for kind, topic in (("added", TOPIC_ADDED), ("removed", TOPIC_REMOVED), ("destroyed", TOPIC_DESTROYED)):
        for ev in _eth_events(topic):
            hist.setdefault(ev["address"], []).append({"type": kind, **ev})
    for evs in hist.values():
        evs.sort(key=lambda e: (e["block"], e["log_index"]))
    return hist


def freeze_events(chain: str, after: str | None = None, before: str | None = None) -> list[dict]:
    """Every AddedBlackList (freeze) on `chain` in [after, before], oldest first.
    -> [{"address", "frozen_at", "freeze_tx", "block"}]"""
    lo = eth.parse_time(after) if after else None
    hi = eth.parse_time(before) if before else None
    out = []
    for addr, evs in _history(chain).items():
        for e in evs:
            if e["type"] != "added":
                continue
            ts = eth.parse_time(e["time"])
            if (lo is not None and ts < lo) or (hi is not None and ts > hi):
                continue
            out.append({"address": addr, "frozen_at": e["time"], "freeze_tx": e["tx"], "block": e["block"]})
    out.sort(key=lambda e: e["block"])
    if not out:
        log.warning("EMPTY freeze_events for %s after=%s before=%s", chain, after, before)
    return out


def is_blacklisted_onchain(chain: str, address: str) -> bool:
    if chain != "ethereum":
        from . import tron
        return tron.is_blacklisted(address)
    res = eth.eth_call(eth.USDT, SEL_IS_BLACKLISTED + eth._pad(address), ttl=300)
    if not res or res == "0x":
        raise ChainAPIError(f"empty isBlackListed result for {address}")
    return int(res, 16) != 0


def _status_from(evs: list[dict]) -> str:
    """frozen | unfrozen | destroyed | none, from a chronological event list."""
    state = "none"
    for e in evs:
        if e["type"] == "added":
            state = "frozen"
        elif e["type"] == "removed":
            state = "unfrozen"
        elif e["type"] == "destroyed" and state == "frozen":
            state = "destroyed"  # still blacklisted, and Tether burned the balance
    return state


def _before(e: dict, as_of: int | str) -> bool:
    if isinstance(as_of, int):
        return e["block"] is not None and e["block"] <= as_of
    return eth.parse_time(e["time"]) <= eth.parse_time(as_of)


def freeze_status(chain: str, address: str, as_of: int | str | None = None) -> dict[str, Any]:
    """-> {"is_frozen", "frozen_at", "freeze_tx", "status": frozen|unfrozen|destroyed|none} + extras
    ("unfrozen_at", "destroyed_usdt", "destroyed_at").

    as_of None: current state, checked on-chain (isBlackListed) and timed from the event history.
    as_of block number or ISO time: local lookup in the event history up to that point (replays).
    """
    if chain == "ethereum":
        address = eth.norm(address)
    else:
        from . import tron
        address = tron.norm(address)
    evs = _history(chain).get(address, [])
    if as_of is not None:
        evs = [e for e in evs if _before(e, as_of)]
    status = _status_from(evs)
    if as_of is None:
        onchain = is_blacklisted_onchain(chain, address)
        if onchain and status not in ("frozen", "destroyed"):
            log.warning("%s is blacklisted on-chain but the event history says %s", address, status)
            status = "frozen"
        elif not onchain and status in ("frozen", "destroyed"):
            log.warning("%s: events say %s but isBlackListed is false; trusting the contract", address, status)
            status = "unfrozen"
    frozen = status in ("frozen", "destroyed")
    added = [e for e in evs if e["type"] == "added"]
    removed = [e for e in evs if e["type"] == "removed"]
    destroyed = [e for e in evs if e["type"] == "destroyed"]
    last_add = added[-1] if added else None
    out: dict[str, Any] = {
        "is_frozen": frozen,
        "frozen_at": last_add["time"] if (frozen and last_add) else None,
        "freeze_tx": last_add["tx"] if (frozen and last_add) else None,
        "status": status,
    }
    if status == "unfrozen" and removed:
        out["unfrozen_at"] = removed[-1]["time"]
        out["previously_frozen_at"] = last_add["time"] if last_add else None
    if destroyed:
        out["destroyed_usdt"] = round(sum(e.get("amount", 0.0) for e in destroyed), 6)
        out["destroyed_at"] = destroyed[-1]["time"]
    return out
