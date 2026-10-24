"""Weekend scan: which recently reported scam addresses still hold unfrozen USDT?

Uses Chainabuse reports (budgeted) + direct USDT balance / blacklist reads. Output
is labelled "reported, not proven". Also the gold-case hunt for the demo: the
best candidate is the reported Ethereum address with the largest unfrozen USDT
balance; it is written to data/cases/gold_candidates.json for review.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hound.proof.chainabuse import chainabuse_reports
from hound.proof.ethcall import usdt_balance, usdt_is_blacklisted

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data" / "cases" / "gold_candidates.json"
CATEGORIES = ("PIGBUTCHERING", "ROMANCE", "FAKE_RETURNS", "OTHER_INVESTMENT_SCAM")


def weekend_scan(categories: tuple[str, ...] = CATEGORIES, since: str | None = None, min_usdt: float = 100.0) -> dict[str, Any]:
    reported: dict[str, dict[str, Any]] = {}
    for cat in categories:
        for r in chainabuse_reports(chain="ethereum", since=since, category=cat):
            cur = reported.setdefault(r["address"], r)
            if cur is not r:
                cur["report_count"] += r["report_count"]
                cur["report_ids"] = sorted(set(cur["report_ids"]) | set(r["report_ids"]))
                cur["confidence"] = max(cur["confidence"], r["confidence"])
    cases = []
    for addr, r in reported.items():
        try:
            bal = usdt_balance(addr)
            frozen = usdt_is_blacklisted(addr)
        except Exception as e:  # noqa: BLE001
            print(f"[scan] {addr}: {e}")
            continue
        r = r | {"balance_usdt": bal, "is_frozen": frozen, "freezable_now": (bal >= min_usdt and not frozen)}
        cases.append(r)
        time.sleep(0.2)
    cases.sort(key=lambda c: (-c["freezable_now"], -c["balance_usdt"]))
    unfrozen = [c for c in cases if c["freezable_now"]]
    result = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "label": "reported, not proven",
        "addresses": len(cases),
        "usdt_unfrozen": round(sum(c["balance_usdt"] for c in unfrozen), 2),
        "addresses_unfrozen": len(unfrozen),
        "already_frozen": sum(c["is_frozen"] for c in cases),
        "cases": cases,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump(result, open(OUT, "w"), indent=1)
    return result


if __name__ == "__main__":
    res = weekend_scan()
    print(json.dumps({k: v for k, v in res.items() if k != "cases"}, indent=2))
    for c in res["cases"][:10]:
        print(c["address"], c["category"], "reports", c["report_count"], "bal", round(c["balance_usdt"]), "frozen", c["is_frozen"])
