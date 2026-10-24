"""Weekend scan: which recently reported scam addresses still hold unfrozen USDT?

Uses Chainabuse reports (budgeted) + direct USDT balance / blacklist reads. Output
is labelled "reported, not proven". Also the gold-case hunt for the demo: the
best candidate is the reported Ethereum address with the largest unfrozen USDT
balance; it is written to data/cases/gold_candidates.json for review.
"""
from __future__ import annotations

import json
import re
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
MAX_LIFETIME_TRANSFERS = 2000  # AUDIT 24: above this the wallet is exchange/service sized, never a scam wallet we can claim
ROW_LABEL = "reported, not proven"
_COUNT_NOT_MEASURED = {"transfer count not checked", "transfer count unavailable"}
METHOD = ("We took every Ethereum address that members of the public reported to Chainabuse as a pig butchering, "
          "romance, fake returns or other investment scam. For each address we read two things straight from the "
          "USDT token contract: how much USDT it holds now, and whether Tether has frozen it. We then left out "
          "exchanges, payment services and shared infrastructure, the USDT contract itself, and any wallet with more "
          "than 2,000 token transfers in its lifetime, because a wallet that busy belongs to a business, not to one "
          "scam. A wallet is also left out if we could not count its transfers. Each remaining wallet counts the "
          "smaller of its balance and the losses its reporters claimed. These are reports, not proven cases.")
_FULL_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")


EXPLORER_ROW_CAP = 1000  # Etherscan-style APIs return at most this many rows per call, whatever offset asks for
USDT_CONTRACT = "0xdac17f958d2ee523a2206206994597c13d831ec7"  # reports name the token itself; it is never a scam wallet


def transfer_count(address: str) -> int:
    """Lifetime ERC-20 transfers of `address`, counted exactly up to MAX_LIFETIME_TRANSFERS + 1.

    Pages of EXPLORER_ROW_CAP rows (one call returns at most that many, so a single call reads a
    capped 1,000 as a real count), Blockscout first, Etherscan as the fallback."""
    from hound.chain.eth import explorer, v1_sources
    sources = ["blockscout"] + [s for s in v1_sources() if s != "blockscout"]
    n, page = 0, 1
    while n <= MAX_LIFETIME_TRANSFERS:
        params = {"module": "account", "action": "tokentx", "address": address, "startblock": 0,
                  "endblock": 99999999, "page": page, "offset": EXPLORER_ROW_CAP, "sort": "asc"}
        got = len(explorer(params, sources=sources)["result"] or [])
        n += got
        if got < EXPLORER_ROW_CAP:
            break
        page += 1
    return n


def _short(address: str) -> str:
    return f"{address[:6]}\u2026{address[-4:]}" if _FULL_ADDR.match(address or "") else address


def finalize(result: dict[str, Any], min_usdt: float = 100.0) -> dict[str, Any]:
    """Re-derive every row's verdict and the headline from the rows themselves (AUDIT 24), so the
    headline is always exactly the sum of the freezable rows' capped amounts.

    Fail closed. A row is excluded when it carries an exchange/service/infra/sanctioned label, has
    more than MAX_LIFETIME_TRANSFERS lifetime transfers, is the USDT contract, has an unpaged count of
    exactly EXPLORER_ROW_CAP (saturated, not measured), has no transfer count (never measured, or
    the read failed), or arrived with freezable_now false and is not frozen (the source scan or an
    earlier finalize excluded it; a row is never promoted here). Each row counts
    min(balance, claimed losses); when no claimed-loss figure was stored (older summaries), it
    counts its balance and says so in cap_basis.
    """
    as_of = result.get("scanned_at")
    cases = []
    for c in result.get("cases", []):
        c = dict(c)
        bal = float(c.get("balance_usdt") or 0.0)
        reasons = []
        addr = str(c.get("address") or "").lower()
        if c.get("label") or c.get("excluded_as_exchange_or_infra"):
            reasons.append("exchange/service/infra label")
        if addr in (USDT_CONTRACT, _short(USDT_CONTRACT).lower()):  # summaries keep only the truncated form
            reasons.append("the USDT token contract itself")
        tc = c.get("transfer_count")
        if tc is not None and tc > MAX_LIFETIME_TRANSFERS:
            reasons.append(f">{MAX_LIFETIME_TRANSFERS:,} lifetime transfers")
        elif tc == EXPLORER_ROW_CAP and not c.get("transfer_count_paged"):
            # a single explorer call stops at 1,000 rows: this count is the cap, not a measurement
            reasons.append(f"transfer count saturated at the explorer's {EXPLORER_ROW_CAP:,}-row cap")
        if c.get("transfer_count_error"):
            reasons.append("transfer count unavailable")
        elif tc is None:
            reasons.append("transfer count not checked")
        if c.get("freezable_now") is False and not c.get("is_frozen") and not reasons:
            reasons.append("excluded in source scan")
        claimed = c.get("claimed_losses_usd")
        if claimed is None:
            capped, basis = bal, "balance (no claimed-loss figure stored for this row)"
        else:
            capped, basis = min(bal, float(claimed)), "min(balance, claimed losses)"
        if not reasons and not c.get("is_frozen") and bal >= min_usdt and capped < min_usdt:
            print(f"[scan] {_short(c.get('address', ''))}: dropped, claimed-loss cap {capped:.2f} is under {min_usdt}")
        c["capped_usdt"] = round(capped, 2)
        c["cap_basis"] = basis
        c["excluded_reasons"] = reasons
        c["freezable_now"] = bool(not c.get("is_frozen") and not reasons and capped >= min_usdt)
        c["row_label"] = ROW_LABEL
        c["as_of"] = c.get("as_of") or as_of
        cases.append(c)
    cases.sort(key=lambda c: (-c["freezable_now"], -c["capped_usdt"], -float(c.get("balance_usdt") or 0)))
    unfrozen = [c for c in cases if c["freezable_now"]]
    return result | {
        "label": ROW_LABEL,
        "usdt_unfrozen": round(sum(c["capped_usdt"] for c in unfrozen), 2),
        "addresses_unfrozen": len(unfrozen),
        # frozen rows are never counted (only unfrozen candidates pay for it), so a missing count is
        # not a reason to drop them here; any other exclusion (a label, the USDT contract) is
        "already_frozen": sum(bool(c.get("is_frozen")) and set(c["excluded_reasons"]) <= _COUNT_NOT_MEASURED
                              for c in cases),
        "method": METHOD,
        "cases": cases,
    }


def redact(result: dict[str, Any]) -> dict[str, Any]:
    """Public view: truncated addresses, no report ids (BRIEF section 0)."""
    cases = []
    for c in result.get("cases", []):
        c = {k: v for k, v in c.items() if k != "report_ids"}
        c["address"] = _short(c.get("address", ""))
        cases.append(c)
    return result | {"cases": cases}


def weekend_scan(categories: tuple[str, ...] = CATEGORIES, since: str | None = None, min_usdt: float = 100.0) -> dict[str, Any]:
    reported: dict[str, dict[str, Any]] = {}
    for cat in categories:
        for r in group_by_address(chainabuse_reports(chain="ethereum", since=since, category=cat)):
            cur = reported.setdefault(r["address"], r)
            if cur is not r:
                cur["report_count"] += r["report_count"]
                cur["report_ids"] = sorted(set(cur["report_ids"]) | set(r["report_ids"]))
                cur["confidence"] = max(cur["confidence"], r["confidence"])
                if cur.get("claimed_losses_usd") is None or r.get("claimed_losses_usd") is None:
                    cur["claimed_losses_usd"] = cur.get("claimed_losses_usd") or r.get("claimed_losses_usd")
                else:
                    cur["claimed_losses_usd"] += r["claimed_losses_usd"]
    cases = []
    for addr, r in reported.items():
        try:
            bal = usdt_balance(addr)
            frozen = usdt_is_blacklisted(addr)
        except Exception as e:  # noqa: BLE001
            print(f"[scan] {addr}: {e}")
            continue
        lab = _labelled(addr)
        # AUDIT 20: exchange hot wallets, sanctioned and infra addresses are never gold candidates
        r = r | {"balance_usdt": bal, "is_frozen": frozen, "label": lab, "transfer_count": None}
        if bal >= min_usdt and not frozen and lab is None:
            try:  # AUDIT 24: only candidates pay for the count; a failed count excludes the row in finalize()
                r["transfer_count"] = transfer_count(addr)
                r["transfer_count_paged"] = True  # exact up to the limit, so 1,000 is a real count here
            except Exception as e:  # noqa: BLE001
                print(f"[scan] transfer count failed for {addr}: {e}")
                r["transfer_count_error"] = str(e)[:200]
        cases.append(r)
        time.sleep(0.2)
    result = finalize({
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "addresses": len(cases),
        "cases": cases,
    }, min_usdt=min_usdt)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump(result, open(OUT, "w"), indent=1)
    return result


def serve() -> dict[str, Any]:
    """What GET /scan/latest returns: the last batch result. Never scans live in a request
    (that would spend the Chainabuse quota and make network calls on every UI refresh)."""
    for path in (OUT, SUMMARY):
        if path.exists():
            return redact(finalize({"status": "ok", **json.load(open(path))}))
    return {"status": "not_computed", "label": "reported, not proven", "addresses": 0, "usdt_unfrozen": 0.0,
            "addresses_unfrozen": 0, "cases": [],
            "method": "No scan has been run on this machine yet. Run python -m hound.proof.scan to produce one."}


if __name__ == "__main__":
    res = weekend_scan()
    print(json.dumps({k: v for k, v in res.items() if k != "cases"}, indent=2))
    for c in res["cases"][:10]:
        print(c["address"], c["category"], "reports", c["report_count"], "bal", round(c["balance_usdt"]), "capped", c["capped_usdt"], "transfers", c.get("transfer_count"), "frozen", c["is_frozen"])
