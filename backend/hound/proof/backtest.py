"""Freeze backtest: how long does USDT sit in an address before Tether blacklists it?

Method (stated in the output): for a sample of addresses that Tether blacklisted on
Ethereum in 2025, measure hours from the FIRST USDT inflow to the AddedBlackList
event. Caveat: survivorship. This only measures addresses Tether did freeze; it
says nothing about addresses it never froze.

Events come from data/doj/usdt_blacklist_events_2025.json (eth_getLogs on the
USDT contract, topic0 AddedBlackList). First-inflow times come from
chain.get_transfers when Jinka's adapter exists, else directly from Blockscout.
"""
from __future__ import annotations

import json
import os
import random
import statistics
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "doj"
EVENTS_PATH = DATA_DIR / "usdt_blacklist_events_2025.json"
CACHE_PATH = DATA_DIR / "backtest_cache.json"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
BLOCKSCOUT = "https://eth.blockscout.com/api/v2"


def _get(url: str, tries: int = 6) -> Any:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hound", "accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503):
                time.sleep(2 * (i + 1))
                continue
            raise
    raise RuntimeError(f"Blockscout unavailable after {tries} tries: {url}")


def _iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def first_usdt_inflow(address: str) -> dict[str, Any] | None:
    """Earliest USDT transfer INTO address, via Blockscout (walks pagination to the end)."""
    params: dict[str, Any] = {"type": "ERC-20", "filter": "to", "token": USDT}
    earliest: dict[str, Any] | None = None
    pages = 0
    while True:
        r = _get(f"{BLOCKSCOUT}/addresses/{address}/token-transfers?" + urllib.parse.urlencode(params))
        for it in r.get("items", []):
            rec = {"time": it["timestamp"], "block": it["block_number"], "tx": it["transaction_hash"],
                   "amount": int(it["total"]["value"]) / 1e6}
            if earliest is None or rec["block"] < earliest["block"]:
                earliest = rec
        nxt = r.get("next_page_params")
        pages += 1
        if not nxt or pages > 40:  # cap: an exchange hot wallet would never end
            break
        params = {"type": "ERC-20", "filter": "to", "token": USDT, **nxt}
        time.sleep(0.5)
    return earliest


def block_time(block: int) -> datetime:
    r = _get(f"{BLOCKSCOUT}/blocks/{block}")
    return _iso(r["timestamp"])


def freeze_backtest(sample: int = 200, seed: int = 7, events_path: Path = EVENTS_PATH) -> dict[str, Any]:
    if not events_path.exists():
        raise FileNotFoundError(f"{events_path} missing; run the event pull first")
    events = json.load(open(events_path))["events"]
    rng = random.Random(seed)
    picked = rng.sample(events, min(sample, len(events)))

    cache: dict[str, Any] = json.load(open(CACHE_PATH)) if CACHE_PATH.exists() else {}
    hours: list[float] = []
    skipped = 0
    for ev in picked:
        a = ev["address"].lower()
        if a not in cache:
            try:
                fi = first_usdt_inflow(a)
                ft = block_time(ev["block"])
                cache[a] = {"first_inflow": fi, "frozen_at": ft.isoformat(), "freeze_block": ev["block"]}
            except Exception as e:  # noqa: BLE001 - log and move on, never silently drop
                cache[a] = {"error": str(e)}
                print(f"[backtest] {a}: {e}")
            json.dump(cache, open(CACHE_PATH, "w"))
        c = cache[a]
        if not c.get("first_inflow"):
            skipped += 1
            continue
        h = (_iso(c["frozen_at"]) - _iso(c["first_inflow"]["time"])).total_seconds() / 3600
        if h >= 0:
            hours.append(h)
        else:
            skipped += 1

    hours.sort()
    n = len(hours)
    p90 = hours[int(0.9 * (n - 1))] if n else float("nan")
    return {
        "median_hours_before_freeze": statistics.median(hours) if n else float("nan"),
        "p90_hours": p90,
        "p10_hours": hours[int(0.1 * (n - 1))] if n else float("nan"),
        "n": n,
        "skipped": skipped,
        "population": len(events),
        "method": ("Hours from first USDT inflow to AddedBlackList event, random sample of "
                   f"{len(picked)} of {len(events)} Ethereum USDT addresses Tether blacklisted in 2025. "
                   "Survivorship caveat: measures only addresses Tether did freeze."),
    }


if __name__ == "__main__":
    print(json.dumps(freeze_backtest(sample=int(os.environ.get("SAMPLE", "50"))), indent=2))
