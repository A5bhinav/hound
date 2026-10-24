"""check(chain, address): should an exchange withdrawal / wallet send to this address go through?

Order of rules:
  1. OFAC-sanctioned                       -> hold
  2. exchange-owned (labelled)             -> allow (never held; would block all its users)
  3. Tether already froze it               -> hold (the money would be stuck)
  4. labelled service / infrastructure     -> allow with a note (warn for mixers)
  5. on the watchlist                      -> hold / warn / allow per watchlist rules (§0 item 9)
  6. nothing known                         -> allow
"""

from __future__ import annotations

import logging
from typing import Any

from .. import chain
from . import watchlist as wl

log = logging.getLogger("hound.watch.check")


def _result(decision: str, reasons: list[str], confidence: float, evidence: dict) -> dict:
    return {"decision": decision, "reasons": reasons, "evidence": evidence, "confidence": round(confidence, 2),
            "label_note": "reported, not proven"}


def check(chain_name: str, address: str, watch: wl.Watchlist | None = None) -> dict[str, Any]:
    """-> {"decision": "allow|warn|hold", "reasons": [str], "evidence": {...}, "confidence": float}"""
    if chain_name not in chain.CHAINS:
        raise ValueError(f"unknown chain {chain_name!r}")
    if chain_name == "ethereum":
        from ..chain.eth import norm
    else:
        from ..chain.tron import norm
    addr = norm(address)  # ValueError on bad input -> HTTP 400 in routes.py
    watch = watch or wl.default()
    lb = chain.label(chain_name, addr)
    evidence: dict[str, Any] = {"chain": chain_name, "address": addr, "label": lb}

    if lb and lb["kind"] == "ofac":
        return _result("hold", ["address is on the US Treasury OFAC sanctions list"], 0.99, evidence)

    if lb and lb["kind"] in ("exchange_hot", "exchange_deposit"):
        evidence["exchange"] = lb.get("exchange") or lb["name"]
        return _result("allow", [f"exchange-owned wallet ({lb['name']}): exchange wallets are never held"],
                       0.9, evidence)

    try:
        fz = chain.freeze_status(chain_name, addr)
    except chain.ChainAPIError as e:
        log.error("freeze_status failed for %s: %s", addr, e)
        fz = None
        evidence["freeze_check_error"] = str(e)
    evidence["frozen"] = fz

    entry = watch.lookup(chain_name, addr)
    if entry:
        evidence["watchlist"] = {k: entry[k] for k in ("cases", "traces", "independent_reports", "direct_hit",
                                                       "confidence", "min_depth", "victim_inflow", "evidence")}

    if fz and fz["is_frozen"]:
        reasons = [f"Tether froze this address on {fz['frozen_at'] or 'an unknown date'}: USDT sent here is stuck"]
        if entry:
            reasons += watch.decision(entry)[1]
        return _result("hold", reasons, 0.95, evidence)

    if lb and lb["kind"] == "service":
        if lb.get("category") == "mixer":
            return _result("warn", [f"{lb['name']} is a mixer: funds sent here are very hard to trace or recover"],
                           0.7, evidence)
        return _result("allow", [f"labelled service/infrastructure ({lb['name']}): never held"], 0.6, evidence)

    if entry:
        decision, reasons = watch.decision(entry)
        return _result(decision, reasons, entry["confidence"], evidence)

    reasons = ["no Hound data: not in any traced scam cluster, not frozen, not sanctioned"]
    if fz is None:
        reasons.append("freeze status could not be checked")
    return _result("allow", reasons, 0.5, evidence)
