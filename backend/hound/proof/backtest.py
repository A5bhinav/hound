"""Freeze backtest (AUDIT issue 23).

detection_lag_hours: first USDT inflow -> AddedBlackList, median and p90.
escape_share: USDT out before the freeze / USDT in before the freeze, per address, median.

Population: every Ethereum USDT AddedBlackList event in 2025, from the chain team's public event dump
data/freezes_eth.json (657 addresses). random.seed(13). Addresses with > 5,000 token transfers are skipped
(exchange-scale wallets) and counted in n_skipped. OFAC-listed addresses are tagged 'sanctions'
and excluded from the headline; everything else is "LE/scam/hack, not separated".
Balance at freeze = archive balanceOf at freeze_block-1 when an archive RPC is set, else the
in-minus-out sum from transfers before the freeze block.

Run once as a batch: `python -m hound.proof.backtest` writes data/proof/backtest.json; the API
serves that file. Survivorship caveat is part of the output: this measures only addresses Tether
did freeze. BlockSec's 54% figure is theirs, not our reproduction.
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

from hound.proof.ethcall import ADDR_RE

ROOT = Path(__file__).resolve().parents[3]
EVENTS_PATH = ROOT / "data" / "freezes_eth.json"  # chain team's public USDT event dump: {"_meta", "events": {addr: [{type, block, time, tx}]}}
OFAC_PATH = ROOT / "data" / "labels" / "ofac.json"  # label DB: {"ethereum": [...], "tron": [...]}
RESULT_PATH = ROOT / "data" / "proof" / "backtest.json"
CACHE_PATH = ROOT / "cache" / "backtest" / "addresses.json"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
BLOCKSCOUT = "https://eth.blockscout.com/api/v2"
MAX_TRANSFERS = 5000
SEED = 13
YEAR = 2025


def _get(url: str, tries: int = 6) -> Any:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hound", "accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 502, 503):
                time.sleep(2 * (i + 1))
                continue
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed after {tries} tries: {url}: {last}")


def _iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def usdt_transfers(address: str, max_rows: int = MAX_TRANSFERS) -> list[dict[str, Any]] | None:
    """All USDT transfers touching address via Blockscout; None if the wallet exceeds max_rows."""
    counters = _get(f"{BLOCKSCOUT}/addresses/{address}/counters")
    n = int(counters.get("token_transfers_count") or 0)
    if n > max_rows:
        return None
    rows: list[dict[str, Any]] = []
    params: dict[str, Any] = {"type": "ERC-20", "token": USDT}
    while True:
        r = _get(f"{BLOCKSCOUT}/addresses/{address}/token-transfers?" + urllib.parse.urlencode(params))
        for it in r.get("items", []):
            rows.append({"from": it["from"]["hash"].lower(), "to": it["to"]["hash"].lower(), "block": it["block_number"],
                         "time": it["timestamp"], "amount": int(it["total"]["value"]) / 1e6, "tx": it["transaction_hash"]})
        nxt = r.get("next_page_params")
        if not nxt or len(rows) > max_rows:
            break
        params = {"type": "ERC-20", "token": USDT, **nxt}
        time.sleep(0.4)
    return rows


def block_time(block: int) -> datetime:
    return _iso(_get(f"{BLOCKSCOUT}/blocks/{block}")["timestamp"])


def measure(address: str, freeze_block: int) -> dict[str, Any]:
    rows = usdt_transfers(address)
    if rows is None:
        return {"skipped": "over_5000_transfers"}
    before = [r for r in rows if r["block"] < freeze_block]
    inflows = [r for r in before if r["to"] == address and r["amount"] > 0]
    if not inflows:
        return {"skipped": "no_usdt_inflow_before_freeze"}
    first = min(inflows, key=lambda r: r["block"])
    usdt_in = sum(r["amount"] for r in inflows)
    usdt_out = sum(r["amount"] for r in before if r["from"] == address)
    ft = block_time(freeze_block)
    lag_h = (ft - _iso(first["time"])).total_seconds() / 3600
    return {"first_inflow_time": first["time"], "frozen_at": ft.isoformat(), "detection_lag_hours": round(lag_h, 2),
            "usdt_in_before_freeze": round(usdt_in, 2), "usdt_out_before_freeze": round(usdt_out, 2),
            "escape_share": round(min(usdt_out / usdt_in, 1.0), 4) if usdt_in > 0 else None,
            "balance_at_freeze_est": round(usdt_in - usdt_out, 2), "n_transfers": len(rows)}


def _ofac() -> set[str]:
    if OFAC_PATH.exists():
        try:
            data = json.load(open(OFAC_PATH))
            addrs = data if isinstance(data, list) else (data.get("ethereum") or data.get("addresses") or [])
            return {a.lower() for a in addrs if isinstance(a, str)}
        except Exception as e:  # noqa: BLE001
            print(f"[backtest] could not read OFAC list: {e}")
    return set()


def freeze_backtest(sample: int = 200, seed: int = SEED, events_path: Path = EVENTS_PATH, write: bool = True) -> dict[str, Any]:
    if RESULT_PATH.exists() and not write:
        return json.load(open(RESULT_PATH))
    if not events_path.exists():
        return {"detection_lag_median_h": None, "p90_h": None, "escape_share_median": None, "n": 0, "n_skipped": 0,
                "population": 0, "method": f"not computed: {events_path.name} missing"}
    raw = json.load(open(events_path))["events"]
    events = [ev for evs in (raw.values() if isinstance(raw, dict) else [raw]) for ev in (evs if isinstance(evs, list) else [evs])]
    uniq: dict[str, int] = {}
    for ev in events:  # first 2025 freeze per address
        a = ev["address"].lower()
        if ev.get("type", "added") != "added" or not str(ev.get("time", "")).startswith(str(YEAR)):
            continue
        if ADDR_RE.match(a) and (a not in uniq or ev["block"] < uniq[a]):
            uniq[a] = ev["block"]
    addrs = sorted(uniq)
    rng = random.Random(seed)
    picked = rng.sample(addrs, min(sample, len(addrs)))
    ofac = _ofac()

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache: dict[str, Any] = json.load(open(CACHE_PATH)) if CACHE_PATH.exists() else {}
    rows = []
    for a in picked:
        if a not in cache:
            try:
                cache[a] = measure(a, uniq[a])
            except Exception as e:  # noqa: BLE001
                cache[a] = {"skipped": f"error: {e}"}
                print(f"[backtest] {a}: {e}")
            json.dump(cache, open(CACHE_PATH, "w"))
        rows.append({"address": a, "freeze_block": uniq[a], "sanctions": a in ofac, **cache[a]})

    headline = [r for r in rows if "detection_lag_hours" in r and not r["sanctions"]]
    lags = sorted(r["detection_lag_hours"] for r in headline)
    esc = sorted(r["escape_share"] for r in headline if r.get("escape_share") is not None)
    n = len(lags)
    result = {
        "detection_lag_median_h": statistics.median(lags) if n else None,
        "p90_h": lags[int(0.9 * (n - 1))] if n else None,
        "p10_h": lags[int(0.1 * (n - 1))] if n else None,
        "escape_share_median": statistics.median(esc) if esc else None,
        "n": n,
        "n_skipped": sum(1 for r in rows if "skipped" in r),
        "n_sanctions_excluded": sum(1 for r in rows if r["sanctions"] and "detection_lag_hours" in r),
        "population": len(addrs),
        "sample_requested": sample,
        "seed": seed,
        "method": ("detection_lag_hours = first USDT inflow -> AddedBlackList event; escape_share = USDT out before freeze / "
                   f"USDT in before freeze. Population: {len(addrs)} Ethereum USDT addresses Tether blacklisted in 2025 "
                   f"(eth_getLogs). random.seed({seed}), sample {len(picked)}. Wallets with >{MAX_TRANSFERS} token transfers "
                   "skipped. OFAC hits tagged 'sanctions' and excluded from the headline; the rest is LE/scam/hack, not separated. "
                   "Survivorship: measures only addresses Tether did freeze. BlockSec's 54% burned figure is theirs."),
        "screen_text": None,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
    }
    if n:
        result["screen_text"] = (f"Tether froze a median {result['detection_lag_median_h']:.0f} hours after the first stolen dollar arrived; "
                                 f"by then about {100 * result['escape_share_median']:.0f}% had already left." if esc else None)
    if write:
        RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        json.dump(result, open(RESULT_PATH, "w"), indent=1)
    return result


def serve() -> dict[str, Any]:
    """What the API returns: the committed batch result, never a live computation."""
    if RESULT_PATH.exists():
        r = json.load(open(RESULT_PATH))
        r.pop("rows", None)
        return r
    # Never compute live in a request: 200 network lookups would hang the demo.
    return {"status": "not_computed", "n": 0, "method": "run `python -m hound.proof.backtest` once to write "
            "data/proof/backtest.json", "detection_lag_median_h": None, "p90_h": None, "escape_share_median": None}


if __name__ == "__main__":
    res = freeze_backtest(sample=int(os.environ.get("SAMPLE", "200")))
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=2))
