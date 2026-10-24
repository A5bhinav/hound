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

from hound.proof.chainabuse import chainabuse_reports, group_by_address
from hound.proof.ethcall import usdt_balance, usdt_is_blacklisted

try:  # team label DB (exchanges, OFAC "sanctioned", infra allowlist); optional so proof/ stays importable alone
    from hound.chain import label as chain_label
except Exception:  # noqa: BLE001
    chain_label = None


def _labelled(address: str) -> dict | None:
    """Exchange / sanctioned / infra label from the team label DB, else None."""
    if chain_label is None:
        return None
    try:
        return chain_label("ethereum", address)
    except Exception as e:  # noqa: BLE001
        print(f"[scan] label lookup failed for {address}: {e}")
        return None

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data" / "cases_live" / "scan_latest.json"  # gitignored: live addresses never public
SUMMARY = ROOT / "data" / "proof" / "weekend_scan_summary.json"  # committed, redacted: truncated addresses, no report ids
CATEGORIES = ("PIGBUTCHERING", "ROMANCE", "FAKE_RETURNS", "OTHER_INVESTMENT_SCAM")


def weekend_scan(categories: tuple[str, ...] = CATEGORIES, since: str | None = None, min_usdt: float = 100.0) -> dict[str, Any]:
    reported: dict[str, dict[str, Any]] = {}
    for cat in categories:
        for r in group_by_address(chainabuse_reports(chain="ethereum", since=since, category=cat)):
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
        lab = _labelled(addr)
        r = r | {"balance_usdt": bal, "is_frozen": frozen, "label": lab,
                 # AUDIT 20: exchange hot wallets, sanctioned and infra addresses are never gold candidates
                 "freezable_now": (bal >= min_usdt and not frozen and lab is None)}
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


def serve() -> dict[str, Any]:
    """What GET /scan/latest returns: the last batch result. Never scans live in a request
    (that would spend the Chainabuse quota and make network calls on every UI refresh)."""
    if OUT.exists():
        return {"status": "ok", **json.load(open(OUT))}
    summary = SUMMARY
    if summary.exists():
        return {"status": "ok", **json.load(open(summary))}
    return {"status": "not_computed", "label": "reported, not proven", "addresses": 0, "usdt_unfrozen": 0.0,
            "addresses_unfrozen": 0, "cases": [], "method": "run `python -m hound.proof.scan` to write the result"}


if __name__ == "__main__":
    res = weekend_scan()
    print(json.dumps({k: v for k, v in res.items() if k != "cases"}, indent=2))
    for c in res["cases"][:10]:
        print(c["address"], c["category"], "reports", c["report_count"], "bal", round(c["balance_usdt"]), "frozen", c["is_frozen"])
