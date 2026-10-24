"""Chainabuse (TRM) public report API client with a hard call budget.

Free keys get 10 calls/month, max 50 reports per call. Every raw response is
cached under cache/chainabuse/ (gitignored) so a query is never paid twice, and a
budget file refuses the 11th call unless HOUND_CHAINABUSE_BUDGET is raised.
Auth: HTTP Basic with the API key as both username and password.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE = "https://api.chainabuse.com/v0"
ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = ROOT / "cache" / "chainabuse"
BUDGET_FILE = CACHE_DIR / "budget.json"
CHAIN_MAP = {"ethereum": "ETH", "tron": "TRON"}
CHAIN_BACK = {v: k for k, v in CHAIN_MAP.items()}


class ChainabuseBudgetExceeded(RuntimeError):
    pass


def _key() -> str:
    k = os.environ.get("CHAINABUSE_API_KEY")
    if not k:
        raise RuntimeError("CHAINABUSE_API_KEY not set (see .env.example)")
    return k


def _budget() -> dict[str, Any]:
    if BUDGET_FILE.exists():
        return json.load(open(BUDGET_FILE))
    return {"month": datetime.now(timezone.utc).strftime("%Y-%m"), "calls": 0}


def _spend() -> None:
    b = _budget()
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    if b["month"] != month:
        b = {"month": month, "calls": 0}
    limit = int(os.environ.get("HOUND_CHAINABUSE_BUDGET", "10"))
    if b["calls"] >= limit:
        raise ChainabuseBudgetExceeded(f"Chainabuse budget {b['calls']}/{limit} used this month; raise HOUND_CHAINABUSE_BUDGET only if partner tier was granted")
    b["calls"] += 1
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(b, open(BUDGET_FILE, "w"))


def get_reports(**params: Any) -> dict[str, Any]:
    """Raw GET /reports. Cached forever by query string; one budget unit per uncached call."""
    clean = {k: (str(v).lower() if isinstance(v, bool) else v) for k, v in params.items() if v is not None}
    qs = urllib.parse.urlencode(sorted(clean.items()))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cpath = CACHE_DIR / (hashlib.sha1(qs.encode()).hexdigest() + ".json")
    if cpath.exists():
        return json.load(open(cpath))
    _spend()
    tok = base64.b64encode(f"{_key()}:{_key()}".encode()).decode()
    req = urllib.request.Request(f"{BASE}/reports?{qs}", headers={"Authorization": f"Basic {tok}", "accept": "application/json", "User-Agent": "hound"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    json.dump({"fetched_at": datetime.now(timezone.utc).isoformat(), "query": clean, "response": data}, open(cpath, "w"))
    print(f"[chainabuse] {qs} -> {data.get('count')} reports (budget {_budget()['calls']}/10)")
    return {"fetched_at": datetime.now(timezone.utc).isoformat(), "query": clean, "response": data}


def chainabuse_reports(chain: str | None = None, since: str | None = None, category: str | None = None,
                       per_page: int = 50, page: int = 1) -> list[dict[str, Any]]:
    """§8.4: list of {address, chain, category, reported_at, report_count, confidence}.

    Aggregates per address across the returned reports. confidence: 0.9 if any
    report is checked by Chainabuse moderators, 0.7 if from a trusted contributor,
    else 0.5. report_count counts reports in THIS response naming the address.
    """
    if since is None:
        since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
    res = get_reports(chain=CHAIN_MAP.get(chain, chain) if chain else None, since=since, category=category,
                      perPage=per_page, page=page, orderByField="CREATED_AT", orderByDirection="ASC")
    agg: dict[tuple[str, str], dict[str, Any]] = {}
    for rep in res["response"].get("reports", []):
        for a in rep.get("addresses", []):
            if not a.get("address") or not a.get("chain"):
                continue
            ch = CHAIN_BACK.get(a["chain"], a["chain"].lower())
            addr = a["address"].lower() if ch == "ethereum" else a["address"]
            key = (ch, addr)
            cur = agg.setdefault(key, {"address": addr, "chain": ch, "category": rep.get("scamCategory"),
                                        "reported_at": rep["createdAt"], "report_count": 0, "confidence": 0.5,
                                        "report_ids": [], "losses_usd": 0.0})
            cur["report_count"] += 1
            cur["report_ids"].append(rep["id"])
            cur["reported_at"] = min(cur["reported_at"], rep["createdAt"])
            if rep.get("checked"):
                cur["confidence"] = max(cur["confidence"], 0.9)
            elif rep.get("trusted"):
                cur["confidence"] = max(cur["confidence"], 0.7)
            for loss in rep.get("losses", []) or []:
                if loss.get("asset") == "USD":
                    cur["losses_usd"] += float(loss.get("amount") or 0)
    return sorted(agg.values(), key=lambda x: (-x["report_count"], x["reported_at"]))
