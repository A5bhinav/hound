"""Tether (USDT) freezes: public AddedBlackList / RemovedBlackList / DestroyedBlackFunds events.

Ethereum history lives in data/freezes_eth.json (committed, AUDIT issue 9), built once with
    .venv/bin/python -m hound.chain.freezes dump
and the tail after the dump's head block is refreshed from the chain every 10 minutes.
freeze_status(chain, address, as_of) is a local lookup; with as_of=None it is also
cross-checked against the contract (isBlackListed) when the network is allowed.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from . import cache, eth
from .cache import REPO_ROOT
from .net import ChainAPIError

log = logging.getLogger("hound.chain.freezes")

TOPIC_ADDED = "0x42e160154868087d6bfdc0ca23d96a1c1cfa32f1b72ba9ba27b69b98a0d819dc"  # AddedBlackList(address)
TOPIC_REMOVED = "0xd7e9ec6e6ecd65492dce6bf513cd6867560d49544421d0783ddf06e76c24470c"  # RemovedBlackList(address)
TOPIC_DESTROYED = "0x61e6e66b0d6339b2980aecc6ccc0039736791f0ccde9ed512e789a7fbdd698c6"  # DestroyedBlackFunds(address,uint256)
SEL_IS_BLACKLISTED = "0xe47d6060"  # isBlackListed(address)
DUMP_FILE = REPO_ROOT / "data" / "freezes_eth.json"
EVENT_TOPICS = (("added", TOPIC_ADDED), ("removed", TOPIC_REMOVED), ("destroyed", TOPIC_DESTROYED))


def _eth_events(topic: str, from_block: int = eth.USDT_DEPLOY_BLOCK) -> list[dict]:
    rows = eth.get_logs(eth.USDT, topic, from_block)
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


def _load_dump() -> tuple[int, dict[str, list[dict]]] | None:
    if not DUMP_FILE.exists():
        return None
    d = json.loads(DUMP_FILE.read_text())
    return d["_meta"]["head_block"], d["events"]


def _fetch_events(from_block: int) -> dict[str, list[dict]]:
    hist: dict[str, list[dict]] = {}
    for kind, topic in EVENT_TOPICS:
        for ev in _eth_events(topic, from_block):
            hist.setdefault(ev["address"], []).append({"type": kind, **ev})
    return hist


def _load_history(chain: str) -> dict[str, list[dict]]:
    if chain != "ethereum":
        from . import tron
        return tron.blacklist_history()
    dump = _load_dump()
    if dump is None:
        log.warning("%s missing: fetching the full freeze history (run `python -m hound.chain.freezes dump`)",
                    DUMP_FILE)
        hist = _fetch_events(eth.USDT_DEPLOY_BLOCK)
    else:
        head, events = dump
        hist = {a: [dict(e) for e in evs] for a, evs in events.items()}
        try:
            tail = _fetch_events(head + 1)  # cached 10 min (recent range)
        except (cache.CacheMiss, ChainAPIError) as e:
            log.warning("freeze tail after block %d not refreshed (%s); using the dump only", head, e)
            tail = {}
        for a, evs in tail.items():
            have = {(e["tx"], e["log_index"]) for e in hist.get(a, [])}
            hist.setdefault(a, []).extend(e for e in evs if (e["tx"], e["log_index"]) not in have)
    for evs in hist.values():
        evs.sort(key=lambda e: (e["block"], e["log_index"]))
    return hist


def dump() -> dict:
    """Write data/freezes_eth.json: every Ethereum USDT blacklist event up to ~1 day ago."""
    head = eth._settled_block(eth.latest_block())
    hist = _fetch_events(eth.USDT_DEPLOY_BLOCK)
    events = {}
    for a, evs in sorted(hist.items()):
        keep = sorted((e for e in evs if e["block"] <= head), key=lambda e: (e["block"], e["log_index"]))
        if keep:
            events[a] = keep
    counts = {k: sum(1 for evs in events.values() for e in evs if e["type"] == k) for k, _ in EVENT_TOPICS}
    out = {"_meta": {"head_block": head, "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     "source": "public USDT contract events 0xdac17f958d2ee523a2206206994597c13d831ec7",
                     "topics": dict((k, t) for k, t in EVENT_TOPICS), "counts": counts},
           "events": events}
    DUMP_FILE.parent.mkdir(parents=True, exist_ok=True)
    DUMP_FILE.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    _MEMO.clear()
    return out["_meta"]


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


def freeze_status(chain: str, address: str, as_of: int | str | None = None,
                  check_onchain: bool = True) -> dict[str, Any]:
    """-> {"is_frozen", "frozen_at", "freeze_tx", "status": frozen|unfrozen|destroyed|none} + extras
    ("frozen_block", "unfrozen_at", "destroyed_amount", "destroyed_tx", "destroyed_block", "destroyed_at").

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
    onchain = None
    if as_of is None and check_onchain:
        try:
            onchain = is_blacklisted_onchain(chain, address)
        except (cache.CacheMiss, ChainAPIError) as e:
            log.info("isBlackListed cross-check skipped for %s: %s", address, e)
    if onchain is not None:
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
        "frozen_block": last_add["block"] if (frozen and last_add) else None,
        "checked_onchain": onchain is not None,
    }
    if status == "unfrozen" and removed:
        out["unfrozen_at"] = removed[-1]["time"]
        out["previously_frozen_at"] = last_add["time"] if last_add else None
    if destroyed:
        amt = round(sum(e.get("amount", 0.0) for e in destroyed), 6)
        out.update({"destroyed_amount": amt, "destroyed_usdt": amt, "destroyed_tx": destroyed[-1]["tx"],
                    "destroyed_block": destroyed[-1]["block"], "destroyed_at": destroyed[-1]["time"]})
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    if sys.argv[1:] != ["dump"]:
        sys.exit("usage: python -m hound.chain.freezes dump")
    print(dump())
