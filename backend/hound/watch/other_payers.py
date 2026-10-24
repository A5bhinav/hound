"""Other payers (AUDIT.md issue 6): count PAYMENTS into the trace's entry layer, never sender addresses.

Entry layer = the trace's depth-0 entry node(s) + non-trace senders into the first-swap layer
(depth-1 nodes; likely other victims' pass-throughs, capped at 20). For each entry address we
list inbound payments >= 100 USDT (native ETH counts, at >= MIN_ETH) inside a window ending at
as_of, excluding anything already a trace node. A sender labelled as an exchange gives the row a
source_exchange; it is never counted as a distinct payer.

UI text: "N payments in from M exchanges into K entry addresses". In the DOJ replay, show
"DOJ identified 38 victims/accounts" in a separate slot; never call these rows victims.

payments(trace)      -> full rows {tx_hash, entry_address, source_exchange, amount, token, time, from, ...}
other_payers(trace)  -> the same payments in the current Trace schema shape
                        {address, amount, window_days, source_exchange, confidence}
summary(rows)        -> {"payments", "exchanges", "entry_addresses", "text"}
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .. import chain
from ..chain.eth import iso, parse_time

log = logging.getLogger("hound.watch.other_payers")

REPLAY_AFTER_DAYS = 90  # a trace whose last edge is older than this is a historical replay
MAX_SWAP_LAYER_SENDERS = 20
MIN_USDT = 100.0
MIN_ETH = 0.03  # ~100 USD; there is no price feed, so this is a fixed stand-in (stated in each row)
EXCHANGE_KINDS = ("exchange_hot", "exchange_deposit")


def _as_of(trace: dict) -> tuple[int, bool]:
    times = [parse_time(e["last_time"]) for e in trace.get("edges", []) if e.get("last_time")]
    now = int(time.time())
    if times and max(times) < now - REPLAY_AFTER_DAYS * 86400:
        return max(times), True
    return now, False


def _skip_fetch(ch: str, address: str) -> str | None:
    lb = chain.label(ch, address)
    if lb:
        return f"labelled {lb['kind']} ({lb['name']}): never fetched"
    return None


def _fetch(ch: str, address: str, start: int, end: int, token: str) -> list[dict]:
    try:
        return chain.get_transfers(ch, address, token=token, after=iso(start), as_of=iso(end))
    except chain.TooManyTransfers:
        log.warning("%s is high-volume; not used for other payers", address)
        return []
    except chain.ChainAPIError as e:
        log.error("other payers: %s %s fetch failed: %s", address, token, e)
        return []


def entry_layer(trace: dict, start: int, end: int) -> list[str]:
    nodes = trace.get("nodes", [])
    known = {n["address"] for n in nodes}
    entry = sorted(n["address"] for n in nodes if n.get("depth") == 0)
    swap_layer = sorted(n["address"] for n in nodes if n.get("depth") == 1)
    ch = nodes[0]["chain"] if nodes else "ethereum"
    senders: dict[str, float] = {}
    for a in swap_layer:
        if _skip_fetch(ch, a):
            continue
        for t in _fetch(ch, a, start, end, "USDT"):
            if t["to"] == a and t["from"] not in known and t["amount"] >= MIN_USDT:
                senders[t["from"]] = senders.get(t["from"], 0.0) + t["amount"]
    extra = sorted(senders, key=lambda s: -senders[s])[:MAX_SWAP_LAYER_SENDERS]
    if len(senders) > MAX_SWAP_LAYER_SENDERS:
        log.info("first-swap layer has %d outside senders; capped at %d", len(senders), MAX_SWAP_LAYER_SENDERS)
    return entry + [s for s in extra if s not in entry]


def payments(trace: dict, window_days: int = 7, as_of: str | None = None) -> list[dict]:
    end, replay = _as_of(trace) if as_of is None else (parse_time(as_of), False)
    start = end - window_days * 86400
    nodes = trace.get("nodes", [])
    ch = nodes[0]["chain"] if nodes else "ethereum"
    known = {n["address"] for n in nodes}
    rows: list[dict[str, Any]] = []
    for entry in entry_layer(trace, start, end):
        why = _skip_fetch(ch, entry)
        if why:
            log.info("entry %s skipped: %s", entry, why)
            continue
        native = "ETH" if ch == "ethereum" else None
        for token, minimum in (("USDT", MIN_USDT), (native, MIN_ETH)):
            if token is None:
                continue
            for t in _fetch(ch, entry, start, end, token):
                if t["to"] != entry or t["from"] in known or t["amount"] < minimum:
                    continue
                lb = chain.label(ch, t["from"])
                exch = (lb.get("exchange") or lb["name"]) if lb and lb["kind"] in EXCHANGE_KINDS else None
                rows.append({
                    "tx_hash": t["tx_hash"], "entry_address": entry, "source_exchange": exch,
                    "amount": round(t["amount"], 6), "token": t["token"], "time": t["time"], "from": t["from"],
                    "chain": ch, "window_days": window_days, "window_end": iso(end), "replay": replay,
                    "confidence": 0.7 if exch else 0.6,
                    "threshold": f">= {minimum} {token}" + (" (fixed stand-in for ~100 USD)" if token == "ETH" else ""),
                })
    rows.sort(key=lambda r: (r["time"], r["tx_hash"]))
    if not rows:
        log.warning("no other-payer payments into the entry layer in %d days to %s", window_days, iso(end))
    return rows


def other_payers(trace: dict, window_days: int = 7, as_of: str | None = None) -> list[dict]:
    """Payments in the current Trace schema shape (one row per payment, address = sender)."""
    return [{"address": r["from"], "amount": r["amount"], "window_days": r["window_days"],
             "source_exchange": r["source_exchange"], "confidence": r["confidence"]}
            for r in payments(trace, window_days=window_days, as_of=as_of)]


def summary(rows: list[dict]) -> dict:
    exchanges = sorted({r["source_exchange"] for r in rows if r.get("source_exchange")})
    entries = sorted({r["entry_address"] for r in rows if r.get("entry_address")})
    text = (f"{len(rows)} payment{'s' if len(rows) != 1 else ''} in from {len(exchanges)} "
            f"exchange{'s' if len(exchanges) != 1 else ''} into {len(entries)} entry "
            f"address{'es' if len(entries) != 1 else ''}")
    return {"payments": len(rows), "exchanges": exchanges, "entry_addresses": entries, "text": text}
